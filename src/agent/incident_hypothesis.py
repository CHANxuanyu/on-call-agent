"""Resumable incident-hypothesis step built on evidence artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AgentStatus
from memory.checkpoints import JsonCheckpointStore, PendingVerifier, SessionCheckpoint
from permissions.models import PermissionAction, PermissionDecision
from permissions.policy import PermissionPolicy
from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.incident_hypothesis import (
    IncidentHypothesisBuilderTool,
    IncidentHypothesisOutput,
)
from tools.models import ToolCall, ToolResult
from transcripts.models import (
    CheckpointWrittenEvent,
    ModelStepEvent,
    PermissionDecisionEvent,
    ResumeStartedEvent,
    ToolRequestEvent,
    ToolResultEvent,
    TranscriptEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus
from verifiers.implementations.incident_hypothesis import (
    HypothesisBranch,
    IncidentHypothesisOutcomeVerifier,
)


class HypothesisResumeArtifacts(BaseModel):
    """Durable artifacts consulted by the incident-hypothesis step."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_path: Path
    transcript_path: Path
    previous_checkpoint_id: str
    previous_phase: str
    prior_transcript_event_count: int
    evidence_verifier_passed: bool


class IncidentHypothesisStepRequest(BaseModel):
    """Structured input for the incident-hypothesis continuation step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    resume_reason: str = "Continue from the latest evidence-reading artifacts."


class IncidentHypothesisStepResult(BaseModel):
    """Structured result returned by the incident-hypothesis step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    incident_id: str
    resumed_successfully: bool
    branch: HypothesisBranch
    consulted_artifacts: HypothesisResumeArtifacts
    consumed_evidence_output: EvidenceReadOutput | None = None
    hypothesis_action_name: str | None = None
    verifier_name: str
    runner_status: AgentStatus
    evidence_supported: bool | None = None
    more_follow_up_required: bool
    verifier_result: VerifierResult
    permission_decision: PermissionDecision | None = None
    tool_result: ToolResult | None = None
    hypothesis_output: IncidentHypothesisOutput | None = None
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    insufficiency_reason: str | None = None


@dataclass(slots=True)
class _HypothesisResumeContext:
    checkpoint_path: Path
    transcript_path: Path
    checkpoint: SessionCheckpoint
    transcript_events: tuple[TranscriptEvent, ...]
    evidence_output: EvidenceReadOutput | None
    evidence_verifier_passed: bool


@dataclass(slots=True)
class IncidentHypothesisStep:
    """Consumes one evidence record and builds one verifier-gated incident hypothesis."""

    transcript_root: Path = Path("sessions/transcripts")
    checkpoint_root: Path = Path("sessions/checkpoints")
    tool: IncidentHypothesisBuilderTool = field(default_factory=IncidentHypothesisBuilderTool)
    verifier: IncidentHypothesisOutcomeVerifier = field(
        default_factory=IncidentHypothesisOutcomeVerifier
    )
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)

    async def run(self, request: IncidentHypothesisStepRequest) -> IncidentHypothesisStepResult:
        context = self._load_context(request.session_id)
        step_index = context.checkpoint.current_step + 1
        transcript_store = JsonlTranscriptStore(context.transcript_path)
        checkpoint_store = JsonCheckpointStore(context.checkpoint_path)

        transcript_store.append(
            ResumeStartedEvent(
                session_id=request.session_id,
                step_index=step_index,
                checkpoint_id=context.checkpoint.checkpoint_id,
                reason=request.resume_reason,
            )
        )

        branch, insufficiency_reason = self._select_branch(context)
        evidence_output = context.evidence_output
        transcript_store.append(
            ModelStepEvent(
                session_id=request.session_id,
                step_index=step_index,
                summary=self._model_step_summary(branch, context, evidence_output),
                planned_verifiers=[self.verifier.definition.name],
            )
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        hypothesis_output: IncidentHypothesisOutput | None = None

        if branch is HypothesisBranch.BUILD_HYPOTHESIS:
            permission_decision = self.permission_policy.decide(self.tool.definition)
            transcript_store.append(
                PermissionDecisionEvent(
                    session_id=request.session_id,
                    step_index=step_index,
                    decision=permission_decision,
                )
            )
            if permission_decision.action is not PermissionAction.ALLOW:
                msg = "incident hypothesis tool must remain read-only and allowed by default"
                raise RuntimeError(msg)

            if evidence_output is None:
                msg = "hypothesis branch requires a durable evidence record"
                raise RuntimeError(msg)

            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={"evidence_output": evidence_output.model_dump(mode="json")},
            )
            call_id = f"{request.session_id}-incident-hypothesis-tool"
            transcript_store.append(
                ToolRequestEvent(
                    session_id=request.session_id,
                    step_index=step_index,
                    call_id=call_id,
                    tool_call=tool_call,
                )
            )
            tool_result = await self.tool.execute(tool_call)
            transcript_store.append(
                ToolResultEvent(
                    session_id=request.session_id,
                    step_index=step_index,
                    call_id=call_id,
                    tool_name=self.tool.definition.name,
                    result=tool_result,
                )
            )
            hypothesis_output = self._parse_hypothesis_output(tool_result)

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "evidence_phase": context.checkpoint.current_phase,
                "evidence_verifier_passed": context.evidence_verifier_passed,
                "insufficiency_reason": insufficiency_reason,
                "evidence_output": (
                    evidence_output.model_dump(mode="json")
                    if evidence_output is not None
                    else None
                ),
                "hypothesis_output": (
                    hypothesis_output.model_dump(mode="json")
                    if hypothesis_output is not None
                    else None
                ),
            },
        )
        verifier_result = await self.verifier.verify(verifier_request)
        transcript_store.append(
            VerifierResultEvent(
                session_id=request.session_id,
                step_index=step_index,
                verifier_name=self.verifier.definition.name,
                request=verifier_request,
                result=verifier_result,
            )
        )

        checkpoint = SessionCheckpoint(
            checkpoint_id=f"{request.session_id}-incident-hypothesis",
            session_id=request.session_id,
            incident_id=context.checkpoint.incident_id,
            current_phase=self._current_phase(
                branch=branch,
                verifier_status=verifier_result.status,
                hypothesis_output=hypothesis_output,
            ),
            current_step=step_index,
            selected_skills=context.checkpoint.selected_skills,
            pending_verifier=self._pending_verifier(verifier_request, verifier_result.status),
            summary_of_progress=self._progress_summary(
                branch=branch,
                evidence_output=evidence_output,
                hypothesis_output=hypothesis_output,
                verifier_result=verifier_result,
                insufficiency_reason=insufficiency_reason,
            ),
        )
        checkpoint_store.write(checkpoint)
        transcript_store.append(
            CheckpointWrittenEvent(
                session_id=request.session_id,
                step_index=step_index,
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_path=context.checkpoint_path,
                summary_of_progress=checkpoint.summary_of_progress,
            )
        )

        return IncidentHypothesisStepResult(
            session_id=request.session_id,
            incident_id=context.checkpoint.incident_id,
            resumed_successfully=branch is HypothesisBranch.BUILD_HYPOTHESIS,
            branch=branch,
            consulted_artifacts=HypothesisResumeArtifacts(
                checkpoint_path=context.checkpoint_path,
                transcript_path=context.transcript_path,
                previous_checkpoint_id=context.checkpoint.checkpoint_id,
                previous_phase=context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.transcript_events),
                evidence_verifier_passed=context.evidence_verifier_passed,
            ),
            consumed_evidence_output=evidence_output,
            hypothesis_action_name=(
                self.tool.definition.name if branch is HypothesisBranch.BUILD_HYPOTHESIS else None
            ),
            verifier_name=self.verifier.definition.name,
            runner_status=self._runner_status(branch, verifier_result.status),
            evidence_supported=(
                hypothesis_output.evidence_supported if hypothesis_output is not None else None
            ),
            more_follow_up_required=self._more_follow_up_required(verifier_result.status),
            verifier_result=verifier_result,
            permission_decision=permission_decision,
            tool_result=tool_result,
            hypothesis_output=hypothesis_output,
            checkpoint_path=context.checkpoint_path,
            checkpoint=checkpoint,
            insufficiency_reason=insufficiency_reason,
        )

    def _load_context(self, session_id: str) -> _HypothesisResumeContext:
        checkpoint_path = self.checkpoint_root / f"{session_id}.json"
        transcript_path = self.transcript_root / f"{session_id}.jsonl"
        checkpoint = JsonCheckpointStore(checkpoint_path).load()
        transcript_events = JsonlTranscriptStore(transcript_path).read_all()

        return _HypothesisResumeContext(
            checkpoint_path=checkpoint_path,
            transcript_path=transcript_path,
            checkpoint=checkpoint,
            transcript_events=transcript_events,
            evidence_output=self._latest_evidence_output(transcript_events),
            evidence_verifier_passed=self._latest_evidence_verifier_status(transcript_events)
            is VerifierStatus.PASS,
        )

    def _latest_evidence_output(
        self,
        transcript_events: tuple[TranscriptEvent, ...],
    ) -> EvidenceReadOutput | None:
        for event in reversed(transcript_events):
            if (
                isinstance(event, ToolResultEvent)
                and event.tool_name == "evidence_bundle_reader"
                and event.result.output
            ):
                return EvidenceReadOutput.model_validate(event.result.output)
        return None

    def _latest_evidence_verifier_status(
        self,
        transcript_events: tuple[TranscriptEvent, ...],
    ) -> VerifierStatus | None:
        for event in reversed(transcript_events):
            if (
                isinstance(event, VerifierResultEvent)
                and event.verifier_name == "incident_evidence_read_outcome"
            ):
                return event.result.status
        return None

    def _select_branch(
        self,
        context: _HypothesisResumeContext,
    ) -> tuple[HypothesisBranch, str | None]:
        if (
            context.checkpoint.current_phase == "evidence_reading_completed"
            and context.evidence_verifier_passed
            and context.evidence_output is not None
        ):
            return HypothesisBranch.BUILD_HYPOTHESIS, None
        if (
            context.checkpoint.current_phase == "evidence_reading_completed"
            and context.evidence_verifier_passed
            and context.evidence_output is None
        ):
            return (
                HypothesisBranch.INSUFFICIENT_STATE,
                "Evidence artifacts indicate a verified evidence record should exist, "
                "but the transcript is missing it.",
            )
        return (
            HypothesisBranch.INSUFFICIENT_STATE,
            "Prior artifacts do not yet contain a verified evidence record for "
            "hypothesis building.",
        )

    def _model_step_summary(
        self,
        branch: HypothesisBranch,
        context: _HypothesisResumeContext,
        evidence_output: EvidenceReadOutput | None,
    ) -> str:
        if branch is HypothesisBranch.BUILD_HYPOTHESIS and evidence_output is not None:
            return (
                f"Resume recovered evidence snapshot {evidence_output.snapshot_id} from "
                "durable artifacts and will build one deterministic incident hypothesis."
            )
        return (
            f"Resume did not find a usable verified evidence record in phase "
            f"{context.checkpoint.current_phase}, so the incident-hypothesis step will record "
            "an insufficient-state branch."
        )

    def _parse_hypothesis_output(
        self,
        tool_result: ToolResult,
    ) -> IncidentHypothesisOutput | None:
        if not tool_result.output:
            return None
        return IncidentHypothesisOutput.model_validate(tool_result.output)

    def _current_phase(
        self,
        branch: HypothesisBranch,
        verifier_status: VerifierStatus,
        hypothesis_output: IncidentHypothesisOutput | None,
    ) -> str:
        if verifier_status is VerifierStatus.UNVERIFIED:
            return "hypothesis_unverified"
        if verifier_status is VerifierStatus.FAIL:
            return "hypothesis_failed_verification"
        if branch is HypothesisBranch.INSUFFICIENT_STATE:
            return "hypothesis_deferred"
        if hypothesis_output is None:
            return "hypothesis_unverified"
        if hypothesis_output.evidence_supported:
            return "hypothesis_supported"
        return "hypothesis_insufficient_evidence"

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
        branch: HypothesisBranch,
        evidence_output: EvidenceReadOutput | None,
        hypothesis_output: IncidentHypothesisOutput | None,
        verifier_result: VerifierResult,
        insufficiency_reason: str | None,
    ) -> str:
        if branch is HypothesisBranch.INSUFFICIENT_STATE:
            return (
                f"Incident hypothesis step deferred. Reason: {insufficiency_reason} "
                f"Verifier status: {verifier_result.status}."
            )
        if evidence_output is None or hypothesis_output is None:
            return (
                "Incident hypothesis step did not produce a structured hypothesis. "
                f"Verifier status: {verifier_result.status}."
            )
        return (
            f"Incident hypothesis step used snapshot {evidence_output.snapshot_id} and produced "
            f"{hypothesis_output.hypothesis_type}. Verifier status: {verifier_result.status}."
        )

    def _runner_status(
        self,
        branch: HypothesisBranch,
        verifier_status: VerifierStatus,
    ) -> AgentStatus:
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        if verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if branch is HypothesisBranch.BUILD_HYPOTHESIS:
            return AgentStatus.RUNNING
        return AgentStatus.VERIFYING

    def _more_follow_up_required(self, verifier_status: VerifierStatus) -> bool:
        return True
