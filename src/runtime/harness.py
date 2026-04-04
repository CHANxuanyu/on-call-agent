"""Thin shared harness for resumable verifier-gated slices."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import JsonCheckpointStore, PendingVerifier, SessionCheckpoint
from permissions.models import PermissionAction, PermissionDecision
from permissions.policy import PermissionPolicy
from runtime.execution import (
    execute_tool_with_invariants,
    execute_verifier_with_invariants,
    normalize_tool_output,
)
from runtime.models import SyntheticFailure
from tools.base import Tool
from tools.models import ToolCall, ToolResult
from transcripts.models import (
    CheckpointWrittenEvent,
    ModelStepEvent,
    PermissionDecisionEvent,
    ResumeStartedEvent,
    ToolRequestEvent,
    ToolResultEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import Verifier, VerifierRequest, VerifierResult, VerifierStatus

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ToolExecutionOutcome(Generic[OutputModelT]):
    """Normalized outcome of one harness-managed tool action."""

    permission_decision: PermissionDecision
    call_id: str
    tool_call: ToolCall
    tool_result: ToolResult
    output: OutputModelT | None


@dataclass(slots=True)
class ResumableSliceHarness:
    """Small execution helper for one resumable slice run."""

    step_name: str
    artifact_context: SessionArtifactContext
    transcript_store: JsonlTranscriptStore
    checkpoint_store: JsonCheckpointStore

    @classmethod
    def load(
        cls,
        *,
        session_id: str,
        step_name: str,
        checkpoint_root: Path = Path("sessions/checkpoints"),
        transcript_root: Path = Path("sessions/transcripts"),
        working_memory_root: Path | None = None,
    ) -> ResumableSliceHarness:
        artifact_context = SessionArtifactContext.load(
            session_id,
            checkpoint_root=checkpoint_root,
            transcript_root=transcript_root,
            working_memory_root=working_memory_root,
        )
        return cls.from_artifact_context(
            step_name=step_name,
            artifact_context=artifact_context,
        )

    @classmethod
    def from_artifact_context(
        cls,
        *,
        step_name: str,
        artifact_context: SessionArtifactContext,
    ) -> ResumableSliceHarness:
        return cls(
            step_name=step_name,
            artifact_context=artifact_context,
            transcript_store=JsonlTranscriptStore(artifact_context.transcript_path),
            checkpoint_store=JsonCheckpointStore(artifact_context.checkpoint_path),
        )

    @property
    def session_id(self) -> str:
        """Return the session id for the current slice run."""

        return self.artifact_context.session_id

    @property
    def checkpoint(self) -> SessionCheckpoint:
        """Return the currently loaded checkpoint."""

        return self.artifact_context.checkpoint

    @property
    def step_index(self) -> int:
        """Return the next step index for this resumable slice."""

        return self.checkpoint.current_step + 1

    def emit_resume_started(self, *, reason: str) -> None:
        """Record the durable start marker for this resumed slice."""

        self.transcript_store.append(
            ResumeStartedEvent(
                session_id=self.session_id,
                step_index=self.step_index,
                checkpoint_id=self.checkpoint.checkpoint_id,
                reason=reason,
            )
        )

    def emit_model_step(
        self,
        *,
        summary: str,
        planned_verifiers: list[str],
        selected_skills: list[str] | None = None,
    ) -> None:
        """Record the slice-local planning/model step note."""

        self.transcript_store.append(
            ModelStepEvent(
                session_id=self.session_id,
                step_index=self.step_index,
                summary=summary,
                selected_skills=selected_skills or [],
                planned_verifiers=planned_verifiers,
            )
        )

    async def execute_read_only_tool(
        self,
        *,
        tool: Tool,
        permission_policy: PermissionPolicy,
        tool_call: ToolCall,
        call_id: str,
        output_model: type[OutputModelT],
        permission_denied_message: str,
    ) -> ToolExecutionOutcome[OutputModelT]:
        """Run one read-only tool action with transcripted invariants."""

        permission_decision = permission_policy.decide(
            tool.definition,
            notes=[
                (
                    f"Step '{self.step_name}' evaluated this tool through the shared "
                    "resumable-slice harness."
                ),
            ],
        )
        self.transcript_store.append(
            PermissionDecisionEvent(
                session_id=self.session_id,
                step_index=self.step_index,
                decision=permission_decision,
            )
        )
        if permission_decision.action is not PermissionAction.ALLOW:
            raise RuntimeError(permission_denied_message)

        self.transcript_store.append(
            ToolRequestEvent(
                session_id=self.session_id,
                step_index=self.step_index,
                call_id=call_id,
                tool_call=tool_call,
            )
        )
        tool_result = await execute_tool_with_invariants(
            step_name=self.step_name,
            tool_name=tool.definition.name,
            execute=lambda: tool.execute(tool_call),
        )
        tool_result, output = normalize_tool_output(
            step_name=self.step_name,
            tool_name=tool.definition.name,
            tool_result=tool_result,
            output_model=output_model,
        )
        self.transcript_store.append(
            ToolResultEvent(
                session_id=self.session_id,
                step_index=self.step_index,
                call_id=call_id,
                tool_name=tool.definition.name,
                result=tool_result,
            )
        )
        return ToolExecutionOutcome(
            permission_decision=permission_decision,
            call_id=call_id,
            tool_call=tool_call,
            tool_result=tool_result,
            output=output,
        )

    async def execute_verifier(
        self,
        *,
        verifier: Verifier,
        request: VerifierRequest,
    ) -> VerifierResult:
        """Run one verifier and record its structured result."""

        verifier_result = await execute_verifier_with_invariants(
            step_name=self.step_name,
            verifier_name=verifier.definition.name,
            execute=lambda: verifier.verify(request),
        )
        self.transcript_store.append(
            VerifierResultEvent(
                session_id=self.session_id,
                step_index=self.step_index,
                verifier_name=verifier.definition.name,
                request=request,
                result=verifier_result,
            )
        )
        return verifier_result

    def write_checkpoint(self, checkpoint: SessionCheckpoint) -> Path:
        """Persist the next checkpoint and emit its transcript marker."""

        checkpoint_path = self.checkpoint_store.write(checkpoint)
        self.transcript_store.append(
            CheckpointWrittenEvent(
                session_id=self.session_id,
                step_index=self.step_index,
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_path=checkpoint_path,
                summary_of_progress=checkpoint.summary_of_progress,
            )
        )
        return checkpoint_path


def pending_verifier_for_status(
    *,
    verifier_name: str,
    verifier_request: VerifierRequest,
    verifier_status: VerifierStatus,
) -> PendingVerifier | None:
    """Return a durable pending-verifier pointer for non-passing states."""

    if verifier_status is VerifierStatus.PASS:
        return None
    return PendingVerifier(
        verifier_name=verifier_name,
        request=verifier_request,
    )


def combine_artifact_failure(
    *,
    prior_failure: SyntheticFailure | None,
    tool_result: ToolResult | None,
    verifier_result: VerifierResult,
) -> SyntheticFailure | None:
    """Collapse prior, tool, and verifier failures into one step-visible failure."""

    if prior_failure is not None:
        return prior_failure
    if tool_result is not None and tool_result.failure is not None:
        return tool_result.failure.synthetic_failure
    return verifier_result.synthetic_failure
