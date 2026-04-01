"""Resumable evidence-reading step built on follow-up artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AgentStatus
from memory.checkpoints import JsonCheckpointStore, PendingVerifier, SessionCheckpoint
from permissions.models import PermissionAction, PermissionDecision
from permissions.policy import PermissionPolicy
from tools.implementations.evidence_reading import EvidenceBundleReaderTool, EvidenceReadOutput
from tools.implementations.follow_up_investigation import (
    FollowUpInvestigationOutput,
    InvestigationTarget,
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
from verifiers.implementations.evidence_reading import (
    EvidenceReadBranch,
    EvidenceReadOutcomeVerifier,
)


class EvidenceResumeArtifacts(BaseModel):
    """Durable artifacts consulted by the evidence-reading step."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_path: Path
    transcript_path: Path
    previous_checkpoint_id: str
    previous_phase: str
    prior_transcript_event_count: int
    follow_up_verifier_passed: bool


class IncidentEvidenceStepRequest(BaseModel):
    """Structured input for the evidence-reading continuation step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    resume_reason: str = "Continue from the latest follow-up investigation artifacts."


class IncidentEvidenceStepResult(BaseModel):
    """Structured result returned by the evidence-reading step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    incident_id: str
    resumed_successfully: bool
    branch: EvidenceReadBranch
    consulted_artifacts: EvidenceResumeArtifacts
    selected_investigation_target: InvestigationTarget | None = None
    evidence_action_name: str | None = None
    verifier_name: str
    runner_status: AgentStatus
    more_follow_up_required: bool
    verifier_result: VerifierResult
    permission_decision: PermissionDecision | None = None
    tool_result: ToolResult | None = None
    evidence_output: EvidenceReadOutput | None = None
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    insufficiency_reason: str | None = None


@dataclass(slots=True)
class _EvidenceResumeContext:
    checkpoint_path: Path
    transcript_path: Path
    checkpoint: SessionCheckpoint
    transcript_events: tuple[TranscriptEvent, ...]
    follow_up_output: FollowUpInvestigationOutput | None
    follow_up_verifier_passed: bool


@dataclass(slots=True)
class IncidentEvidenceStep:
    """Consumes a durable follow-up target and reads one deterministic evidence snapshot."""

    transcript_root: Path = Path("sessions/transcripts")
    checkpoint_root: Path = Path("sessions/checkpoints")
    tool: EvidenceBundleReaderTool = field(default_factory=EvidenceBundleReaderTool)
    verifier: EvidenceReadOutcomeVerifier = field(default_factory=EvidenceReadOutcomeVerifier)
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)

    async def run(self, request: IncidentEvidenceStepRequest) -> IncidentEvidenceStepResult:
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
        selected_target = (
            context.follow_up_output.investigation_target
            if context.follow_up_output is not None
            else None
        )
        transcript_store.append(
            ModelStepEvent(
                session_id=request.session_id,
                step_index=step_index,
                summary=self._model_step_summary(branch, context, selected_target),
                planned_verifiers=[self.verifier.definition.name],
            )
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        evidence_output: EvidenceReadOutput | None = None

        if branch is EvidenceReadBranch.READ_EVIDENCE:
            permission_decision = self.permission_policy.decide(self.tool.definition)
            transcript_store.append(
                PermissionDecisionEvent(
                    session_id=request.session_id,
                    step_index=step_index,
                    decision=permission_decision,
                )
            )
            if permission_decision.action is not PermissionAction.ALLOW:
                msg = "evidence-reading tool must remain read-only and allowed by default"
                raise RuntimeError(msg)

            if context.follow_up_output is None:
                msg = "evidence-reading branch requires a durable follow-up target"
                raise RuntimeError(msg)

            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={
                    "investigation_output": context.follow_up_output.model_dump(mode="json")
                },
            )
            call_id = f"{request.session_id}-evidence-reader-tool"
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
            evidence_output = self._parse_evidence_output(tool_result)

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "follow_up_phase": context.checkpoint.current_phase,
                "follow_up_verifier_passed": context.follow_up_verifier_passed,
                "selected_target": selected_target,
                "insufficiency_reason": insufficiency_reason,
                "evidence_output": (
                    evidence_output.model_dump(mode="json")
                    if evidence_output is not None
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
            checkpoint_id=f"{request.session_id}-evidence-read",
            session_id=request.session_id,
            incident_id=context.checkpoint.incident_id,
            current_phase=self._current_phase(
                branch=branch,
                previous_phase=context.checkpoint.current_phase,
                verifier_status=verifier_result.status,
            ),
            current_step=step_index,
            selected_skills=context.checkpoint.selected_skills,
            pending_verifier=self._pending_verifier(verifier_request, verifier_result.status),
            summary_of_progress=self._progress_summary(
                branch=branch,
                selected_target=selected_target,
                evidence_output=evidence_output,
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

        return IncidentEvidenceStepResult(
            session_id=request.session_id,
            incident_id=context.checkpoint.incident_id,
            resumed_successfully=branch is EvidenceReadBranch.READ_EVIDENCE,
            branch=branch,
            consulted_artifacts=EvidenceResumeArtifacts(
                checkpoint_path=context.checkpoint_path,
                transcript_path=context.transcript_path,
                previous_checkpoint_id=context.checkpoint.checkpoint_id,
                previous_phase=context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.transcript_events),
                follow_up_verifier_passed=context.follow_up_verifier_passed,
            ),
            selected_investigation_target=selected_target,
            evidence_action_name=(
                self.tool.definition.name if branch is EvidenceReadBranch.READ_EVIDENCE else None
            ),
            verifier_name=self.verifier.definition.name,
            runner_status=self._runner_status(
                branch=branch,
                previous_phase=context.checkpoint.current_phase,
                verifier_status=verifier_result.status,
            ),
            more_follow_up_required=self._more_follow_up_required(
                branch=branch,
                previous_phase=context.checkpoint.current_phase,
                verifier_status=verifier_result.status,
            ),
            verifier_result=verifier_result,
            permission_decision=permission_decision,
            tool_result=tool_result,
            evidence_output=evidence_output,
            checkpoint_path=context.checkpoint_path,
            checkpoint=checkpoint,
            insufficiency_reason=insufficiency_reason,
        )

    def _load_context(self, session_id: str) -> _EvidenceResumeContext:
        checkpoint_path = self.checkpoint_root / f"{session_id}.json"
        transcript_path = self.transcript_root / f"{session_id}.jsonl"
        checkpoint = JsonCheckpointStore(checkpoint_path).load()
        transcript_events = JsonlTranscriptStore(transcript_path).read_all()

        return _EvidenceResumeContext(
            checkpoint_path=checkpoint_path,
            transcript_path=transcript_path,
            checkpoint=checkpoint,
            transcript_events=transcript_events,
            follow_up_output=self._latest_follow_up_output(transcript_events),
            follow_up_verifier_passed=self._latest_follow_up_verifier_status(transcript_events)
            is VerifierStatus.PASS,
        )

    def _latest_follow_up_output(
        self,
        transcript_events: tuple[TranscriptEvent, ...],
    ) -> FollowUpInvestigationOutput | None:
        for event in reversed(transcript_events):
            if (
                isinstance(event, ToolResultEvent)
                and event.tool_name == "investigation_focus_selector"
                and event.result.output
            ):
                return FollowUpInvestigationOutput.model_validate(event.result.output)
        return None

    def _latest_follow_up_verifier_status(
        self,
        transcript_events: tuple[TranscriptEvent, ...],
    ) -> VerifierStatus | None:
        for event in reversed(transcript_events):
            if (
                isinstance(event, VerifierResultEvent)
                and event.verifier_name == "incident_follow_up_outcome"
            ):
                return event.result.status
        return None

    def _select_branch(
        self,
        context: _EvidenceResumeContext,
    ) -> tuple[EvidenceReadBranch, str | None]:
        if (
            context.checkpoint.current_phase == "follow_up_investigation_selected"
            and context.follow_up_verifier_passed
            and context.follow_up_output is not None
        ):
            return EvidenceReadBranch.READ_EVIDENCE, None
        if context.checkpoint.current_phase == "follow_up_complete_no_action":
            return (
                EvidenceReadBranch.INSUFFICIENT_STATE,
                "Previous follow-up step completed without selecting a "
                "further investigation target.",
            )
        if (
            context.checkpoint.current_phase == "follow_up_investigation_selected"
            and context.follow_up_verifier_passed
            and context.follow_up_output is None
        ):
            return (
                EvidenceReadBranch.INSUFFICIENT_STATE,
                "Follow-up artifacts indicate a selected target should exist, "
                "but the transcript is missing it.",
            )
        return (
            EvidenceReadBranch.INSUFFICIENT_STATE,
            "Prior artifacts do not yet contain a verified selected investigation target.",
        )

    def _model_step_summary(
        self,
        branch: EvidenceReadBranch,
        context: _EvidenceResumeContext,
        selected_target: InvestigationTarget | None,
    ) -> str:
        if branch is EvidenceReadBranch.READ_EVIDENCE:
            return (
                f"Resume recovered selected target {selected_target} from follow-up artifacts and "
                "will read one deterministic local evidence bundle."
            )
        return (
            f"Resume did not find a usable selected investigation target in phase "
            f"{context.checkpoint.current_phase}, so the evidence-reading step will record "
            "an insufficient-state branch."
        )

    def _parse_evidence_output(self, tool_result: ToolResult) -> EvidenceReadOutput | None:
        if not tool_result.output:
            return None
        return EvidenceReadOutput.model_validate(tool_result.output)

    def _current_phase(
        self,
        branch: EvidenceReadBranch,
        previous_phase: str,
        verifier_status: VerifierStatus,
    ) -> str:
        if verifier_status is VerifierStatus.UNVERIFIED:
            return "evidence_reading_unverified"
        if verifier_status is VerifierStatus.FAIL:
            return "evidence_reading_failed_verification"
        if branch is EvidenceReadBranch.READ_EVIDENCE:
            return "evidence_reading_completed"
        if previous_phase == "follow_up_complete_no_action":
            return "evidence_reading_not_applicable"
        return "evidence_reading_deferred"

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
        branch: EvidenceReadBranch,
        selected_target: InvestigationTarget | None,
        evidence_output: EvidenceReadOutput | None,
        verifier_result: VerifierResult,
        insufficiency_reason: str | None,
    ) -> str:
        if branch is EvidenceReadBranch.INSUFFICIENT_STATE:
            return (
                f"Evidence-reading step deferred. Reason: {insufficiency_reason} "
                f"Verifier status: {verifier_result.status}."
            )
        if evidence_output is None:
            return (
                f"Evidence-reading step did not produce structured evidence for "
                f"{selected_target}. Verifier status: {verifier_result.status}."
            )
        return (
            f"Evidence-reading step captured snapshot {evidence_output.snapshot_id} for "
            f"{selected_target}. Verifier status: {verifier_result.status}."
        )

    def _runner_status(
        self,
        branch: EvidenceReadBranch,
        previous_phase: str,
        verifier_status: VerifierStatus,
    ) -> AgentStatus:
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        if verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if branch is EvidenceReadBranch.READ_EVIDENCE:
            return AgentStatus.RUNNING
        if previous_phase == "follow_up_complete_no_action":
            return AgentStatus.COMPLETED
        return AgentStatus.VERIFYING

    def _more_follow_up_required(
        self,
        branch: EvidenceReadBranch,
        previous_phase: str,
        verifier_status: VerifierStatus,
    ) -> bool:
        if verifier_status is not VerifierStatus.PASS:
            return True
        if branch is EvidenceReadBranch.READ_EVIDENCE:
            return True
        return previous_phase != "follow_up_complete_no_action"
