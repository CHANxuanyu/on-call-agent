"""Minimal vertical slice for the incident-triage harness path."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AgentStatus
from memory.checkpoints import JsonCheckpointStore, PendingVerifier, SessionCheckpoint
from permissions.models import PermissionAction, PermissionDecision
from permissions.policy import PermissionPolicy
from skills.loader import SkillLoader
from tools.implementations.incident_triage import (
    IncidentPayloadSummaryTool,
    IncidentTriageInput,
    IncidentTriageOutput,
)
from tools.models import ToolCall, ToolResult
from transcripts.models import (
    CheckpointWrittenEvent,
    ModelStepEvent,
    PermissionDecisionEvent,
    ToolRequestEvent,
    ToolResultEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus
from verifiers.implementations.incident_triage import IncidentTriageOutputVerifier


class IncidentTriageStepRequest(IncidentTriageInput):
    """Structured input accepted by the first triage step."""

    session_id: str = Field(min_length=1)


class IncidentTriageStepResult(BaseModel):
    """Structured result returned by the first triage step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    incident_id: str
    skill_name: str
    skill_path: Path
    transcript_path: Path
    checkpoint_path: Path
    status: AgentStatus
    completed: bool
    permission_decision: PermissionDecision
    tool_result: ToolResult
    triage_output: IncidentTriageOutput | None = None
    verifier_result: VerifierResult
    checkpoint: SessionCheckpoint


@dataclass(slots=True)
class IncidentTriageStep:
    """Runs one explicit incident-triage step over local, deterministic components."""

    skills_root: Path = Path("skills")
    transcript_root: Path = Path("sessions/transcripts")
    checkpoint_root: Path = Path("sessions/checkpoints")
    tool: IncidentPayloadSummaryTool = field(default_factory=IncidentPayloadSummaryTool)
    verifier: IncidentTriageOutputVerifier = field(default_factory=IncidentTriageOutputVerifier)
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)

    async def run(self, request: IncidentTriageStepRequest) -> IncidentTriageStepResult:
        skill = SkillLoader(self.skills_root).load("incident-triage")
        transcript_path = self.transcript_root / f"{request.session_id}.jsonl"
        transcript_store = JsonlTranscriptStore(transcript_path)
        checkpoint_path = self.checkpoint_path(request.session_id)
        checkpoint_store = JsonCheckpointStore(checkpoint_path)

        transcript_store.append(
            ModelStepEvent(
                session_id=request.session_id,
                step_index=1,
                summary=(
                    "Loaded the incident-triage skill and prepared a deterministic read-only "
                    "triage step."
                ),
                selected_skills=[skill.metadata.name],
                planned_verifiers=[self.verifier.definition.name],
            )
        )

        tool_call = ToolCall(
            name=self.tool.definition.name,
            arguments=request.model_dump(mode="json", exclude={"session_id"}),
        )
        permission_decision = self.permission_policy.decide(self.tool.definition)
        transcript_store.append(
            PermissionDecisionEvent(
                session_id=request.session_id,
                step_index=1,
                decision=permission_decision,
            )
        )
        if permission_decision.action is not PermissionAction.ALLOW:
            msg = "incident triage tool must remain read-only and allowed by default"
            raise RuntimeError(msg)

        call_id = f"{request.session_id}-incident-triage-tool"
        transcript_store.append(
            ToolRequestEvent(
                session_id=request.session_id,
                step_index=1,
                call_id=call_id,
                tool_call=tool_call,
            )
        )

        tool_result = await self.tool.execute(tool_call)
        transcript_store.append(
            ToolResultEvent(
                session_id=request.session_id,
                step_index=1,
                call_id=call_id,
                tool_name=self.tool.definition.name,
                result=tool_result,
            )
        )

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=request.incident_id,
            inputs={"triage_output": tool_result.output},
        )
        verifier_result = await self.verifier.verify(verifier_request)
        transcript_store.append(
            VerifierResultEvent(
                session_id=request.session_id,
                step_index=1,
                verifier_name=self.verifier.definition.name,
                request=verifier_request,
                result=verifier_result,
            )
        )

        triage_output = self._parse_triage_output(tool_result)
        checkpoint = SessionCheckpoint(
            checkpoint_id=f"{request.session_id}-incident-triage",
            session_id=request.session_id,
            incident_id=request.incident_id,
            current_phase=self._current_phase(verifier_result.status),
            current_step=1,
            selected_skills=[skill.metadata.name],
            pending_verifier=self._pending_verifier(verifier_request, verifier_result.status),
            summary_of_progress=self._progress_summary(
                request=request,
                triage_output=triage_output,
                verifier_result=verifier_result,
            ),
        )
        checkpoint_store.write(checkpoint)
        transcript_store.append(
            CheckpointWrittenEvent(
                session_id=request.session_id,
                step_index=1,
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_path=checkpoint_path,
                summary_of_progress=checkpoint.summary_of_progress,
            )
        )

        status = self._status_from_verifier(verifier_result.status)
        return IncidentTriageStepResult(
            session_id=request.session_id,
            incident_id=request.incident_id,
            skill_name=skill.metadata.name,
            skill_path=skill.path,
            transcript_path=transcript_path,
            checkpoint_path=checkpoint_path,
            status=status,
            completed=verifier_result.status is VerifierStatus.PASS,
            permission_decision=permission_decision,
            tool_result=tool_result,
            triage_output=triage_output,
            verifier_result=verifier_result,
            checkpoint=checkpoint,
        )

    def checkpoint_path(self, session_id: str) -> Path:
        """Return the stable checkpoint path for a session."""

        return self.checkpoint_root / f"{session_id}.json"

    def _parse_triage_output(self, tool_result: ToolResult) -> IncidentTriageOutput | None:
        if not tool_result.output:
            return None
        return IncidentTriageOutput.model_validate(tool_result.output)

    def _current_phase(self, verifier_status: VerifierStatus) -> str:
        if verifier_status is VerifierStatus.PASS:
            return "triage_completed"
        if verifier_status is VerifierStatus.FAIL:
            return "triage_failed_verification"
        return "triage_unverified"

    def _pending_verifier(
        self,
        verifier_request: VerifierRequest,
        verifier_status: VerifierStatus,
    ) -> PendingVerifier | None:
        if verifier_status is VerifierStatus.PASS:
            return None
        return PendingVerifier(
            verifier_name=self.verifier.definition.name,
            request=verifier_request,
        )

    def _progress_summary(
        self,
        request: IncidentTriageStepRequest,
        triage_output: IncidentTriageOutput | None,
        verifier_result: VerifierResult,
    ) -> str:
        if triage_output is None:
            return (
                f"Triage step for {request.incident_id} did not produce a structured summary. "
                f"Verifier status: {verifier_result.status}."
            )
        return (
            f"Triage step for {request.incident_id} produced suspected severity "
            f"{triage_output.suspected_severity} for {triage_output.service}. "
            f"Verifier status: {verifier_result.status}."
        )

    def _status_from_verifier(self, verifier_status: VerifierStatus) -> AgentStatus:
        if verifier_status is VerifierStatus.PASS:
            return AgentStatus.COMPLETED
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        return AgentStatus.FAILED
