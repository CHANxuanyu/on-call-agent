"""Thin Phase 1 Operator Console API adapters over existing runtime truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from context.handoff_artifact import (
    IncidentHandoffArtifact,
    JsonIncidentHandoffArtifactStore,
)
from context.handoff_regeneration import (
    HandoffArtifactRegenerationResult,
    IncidentHandoffArtifactRegenerator,
)
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import (
    ApprovalState,
    ApprovalStatus,
    JsonCheckpointStore,
    OperatorAutonomyMode,
    PendingVerifier,
)
from runtime.inspect import load_artifact_context
from runtime.live_surface import (
    run_resolve_deployment_regression_approval,
    run_verify_deployment_regression_outcome,
)
from runtime.shell import build_shell_status_payload
from tools.implementations.deployment_outcome_probe import DeploymentOutcomeProbeOutput
from tools.implementations.incident_triage import IncidentTriageInput
from transcripts.models import (
    ApprovalResolvedEvent,
    CheckpointWrittenEvent,
    PermissionDecisionEvent,
    ResumeStartedEvent,
    ToolRequestEvent,
    ToolResultEvent,
    TranscriptEvent,
    TranscriptEventType,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierStatus

_IMPORTANT_TIMELINE_TOOL_NAMES = frozenset(
    {
        "deployment_rollback_executor",
        "deployment_outcome_probe",
    }
)


class ConsoleApprovalDecision(StrEnum):
    """Approval decisions supported by the narrow deployment-regression live surface."""

    APPROVE = "approve"
    DENY = "deny"


class ConsoleTimelineKind(StrEnum):
    """Operator-facing categories for recent timeline activity."""

    CHECKPOINT = "checkpoint"
    VERIFIER = "verifier"
    APPROVAL = "approval"
    PERMISSION = "permission"
    RESUME = "resume"
    EXECUTION = "execution"
    VERIFICATION = "verification"


class ConsoleVerificationStatus(StrEnum):
    """Current availability of the outcome-verification artifact."""

    VERIFIED = "verified"
    INSUFFICIENT = "insufficient"
    FAILED = "failed"


class ConsoleSessionListItem(BaseModel):
    """Compact recent session summary for a sessions view."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    current_phase: str = Field(min_length=1)
    requested_mode: OperatorAutonomyMode
    effective_mode: OperatorAutonomyMode
    approval_status: ApprovalStatus
    latest_verifier_summary: str = Field(min_length=1)
    last_updated: datetime


class ConsoleSessionsResponse(BaseModel):
    """Recent session list grounded in checkpoints and transcript events."""

    model_config = ConfigDict(extra="forbid")

    sessions: list[ConsoleSessionListItem] = Field(default_factory=list)


class ConsoleHandoffAccess(BaseModel):
    """Current handoff artifact availability for one incident session."""

    model_config = ConfigDict(extra="forbid")

    available: bool
    handoff_path: Path
    artifact: IncidentHandoffArtifact | None = None


class ConsoleSessionDetail(BaseModel):
    """Single-session detail view grounded in current runtime truth."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    current_phase: str = Field(min_length=1)
    current_step: int = Field(ge=0)
    summary_of_progress: str = Field(min_length=1)
    requested_mode: OperatorAutonomyMode
    effective_mode: OperatorAutonomyMode
    mode_reason: str | None = None
    approval: ApprovalState
    pending_verifier: PendingVerifier | None = None
    next_recommended_action: str = Field(min_length=1)
    current_evidence_summary: str = Field(min_length=1)
    latest_verifier_summary: str = Field(min_length=1)
    latest_checkpoint_time: datetime
    handoff: ConsoleHandoffAccess


class ConsoleTimelineEntry(BaseModel):
    """One operator-facing timeline entry derived from transcript events."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    step_index: int | None = None
    event_type: TranscriptEventType
    kind: ConsoleTimelineKind
    summary: str = Field(min_length=1)
    tool_name: str | None = None
    verifier_name: str | None = None
    checkpoint_id: str | None = None


class ConsoleSessionTimelineResponse(BaseModel):
    """Recent operator timeline for one session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    entries: list[ConsoleTimelineEntry] = Field(default_factory=list)


class ConsoleVerificationResult(BaseModel):
    """Latest outcome-verification view derived from verified artifacts."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    current_phase: str = Field(min_length=1)
    status: ConsoleVerificationStatus
    verifier_status: VerifierStatus | None = None
    summary: str = Field(min_length=1)
    output: DeploymentOutcomeProbeOutput | None = None
    insufficiency_reason: str | None = None
    failure_reason: str | None = None


class ConsoleApprovalActionResponse(BaseModel):
    """Updated operator state after an approval or denial action."""

    model_config = ConfigDict(extra="forbid")

    approval_decision: ConsoleApprovalDecision
    session: ConsoleSessionDetail
    verification: ConsoleVerificationResult


class ConsoleVerificationActionResponse(BaseModel):
    """Updated operator state after rerunning outcome verification."""

    model_config = ConfigDict(extra="forbid")

    verification_rerun: bool = True
    session: ConsoleSessionDetail
    verification: ConsoleVerificationResult


class ConsoleHandoffExportResponse(BaseModel):
    """Handoff export access over the existing regeneration seam."""

    model_config = ConfigDict(extra="forbid")

    result: HandoffArtifactRegenerationResult
    artifact: IncidentHandoffArtifact | None = None


def _family_from_triage_input(triage_input: IncidentTriageInput | None) -> str:
    if (
        triage_input is not None
        and triage_input.service_base_url is not None
        and triage_input.expected_bad_version is not None
        and triage_input.expected_previous_version is not None
    ):
        return "deployment-regression"
    return "unknown"


def _latest_triage_input_from_events(
    events: tuple[TranscriptEvent, ...],
) -> IncidentTriageInput | None:
    for event in reversed(events):
        if not isinstance(event, ToolRequestEvent):
            continue
        if event.tool_call.name != "incident_payload_summary":
            continue
        try:
            return IncidentTriageInput.model_validate(event.tool_call.arguments)
        except ValidationError:
            return None
    return None


def _latest_verifier_summary_from_events(events: tuple[TranscriptEvent, ...]) -> str:
    for event in reversed(events):
        if isinstance(event, VerifierResultEvent):
            return (
                f"{event.verifier_name}={event.result.status.value}: "
                f"{event.result.summary}"
            )
    return "No verifier result has been recorded yet."


def _timeline_events(
    events: tuple[TranscriptEvent, ...],
    *,
    limit: int,
) -> tuple[TranscriptEvent, ...]:
    filtered = tuple(
        event
        for event in events
        if isinstance(
            event,
            (
                ApprovalResolvedEvent,
                CheckpointWrittenEvent,
                PermissionDecisionEvent,
                ResumeStartedEvent,
                VerifierResultEvent,
            ),
        )
        or (
            isinstance(event, (ToolRequestEvent, ToolResultEvent))
            and _timeline_includes_tool_name(event)
        )
    )
    return filtered[-limit:]


def _timeline_includes_tool_name(event: ToolRequestEvent | ToolResultEvent) -> bool:
    if isinstance(event, ToolRequestEvent):
        return event.tool_call.name in _IMPORTANT_TIMELINE_TOOL_NAMES
    return event.tool_name in _IMPORTANT_TIMELINE_TOOL_NAMES


def _timeline_kind(event: TranscriptEvent) -> ConsoleTimelineKind:
    if isinstance(event, CheckpointWrittenEvent):
        return ConsoleTimelineKind.CHECKPOINT
    if isinstance(event, VerifierResultEvent):
        return ConsoleTimelineKind.VERIFIER
    if isinstance(event, ApprovalResolvedEvent):
        return ConsoleTimelineKind.APPROVAL
    if isinstance(event, PermissionDecisionEvent):
        return ConsoleTimelineKind.PERMISSION
    if isinstance(event, ResumeStartedEvent):
        return ConsoleTimelineKind.RESUME
    if isinstance(event, (ToolRequestEvent, ToolResultEvent)):
        tool_name = event.tool_call.name if isinstance(event, ToolRequestEvent) else event.tool_name
        if tool_name == "deployment_outcome_probe":
            return ConsoleTimelineKind.VERIFICATION
        return ConsoleTimelineKind.EXECUTION
    msg = f"unsupported timeline event type: {type(event).__name__}"
    raise ValueError(msg)


def _timeline_summary(event: TranscriptEvent) -> str:
    if isinstance(event, CheckpointWrittenEvent):
        return event.summary_of_progress
    if isinstance(event, VerifierResultEvent):
        return (
            f"{event.verifier_name}={event.result.status.value}: "
            f"{event.result.summary}"
        )
    if isinstance(event, ApprovalResolvedEvent):
        suffix = f": {event.reason}" if event.reason is not None else ""
        return f"{event.decision} {event.requested_action}{suffix}"
    if isinstance(event, PermissionDecisionEvent):
        return (
            f"{event.decision.action.value} {event.decision.tool_name}: "
            f"{event.decision.reason}"
        )
    if isinstance(event, ResumeStartedEvent):
        return event.reason
    if isinstance(event, ToolRequestEvent):
        return f"requested {event.tool_call.name}"
    if isinstance(event, ToolResultEvent):
        return f"{event.tool_name} returned {event.result.status.value}"
    return event.event_type.value


def _timeline_entry(event: TranscriptEvent) -> ConsoleTimelineEntry:
    tool_name = None
    if isinstance(event, ToolRequestEvent):
        tool_name = event.tool_call.name
    elif isinstance(event, ToolResultEvent):
        tool_name = event.tool_name
    verifier_name = event.verifier_name if isinstance(event, VerifierResultEvent) else None
    checkpoint_id = event.checkpoint_id if isinstance(event, CheckpointWrittenEvent) else None
    return ConsoleTimelineEntry(
        timestamp=event.timestamp,
        step_index=event.step_index,
        event_type=TranscriptEventType(event.event_type),
        kind=_timeline_kind(event),
        summary=_timeline_summary(event),
        tool_name=tool_name,
        verifier_name=verifier_name,
        checkpoint_id=checkpoint_id,
    )


@dataclass(slots=True)
class OperatorConsoleAPI:
    """Thin Phase 1 backend adapter over checkpoints, transcripts, and handoff artifacts."""

    checkpoint_root: Path = Path("sessions/checkpoints")
    transcript_root: Path = Path("sessions/transcripts")
    handoff_root: Path = Path("sessions/handoffs")

    @property
    def working_memory_root(self) -> Path:
        return self.checkpoint_root.parent / "working_memory"

    def list_sessions(self, *, limit: int | None = None) -> ConsoleSessionsResponse:
        if limit is not None and limit < 1:
            msg = "limit must be greater than zero"
            raise ValueError(msg)
        if not self.checkpoint_root.exists():
            return ConsoleSessionsResponse()

        sessions: list[ConsoleSessionListItem] = []
        for checkpoint_path in sorted(self.checkpoint_root.glob("*.json")):
            try:
                checkpoint = JsonCheckpointStore(checkpoint_path).load()
            except (OSError, ValidationError, ValueError):
                continue

            transcript_path = self.transcript_root / f"{checkpoint.session_id}.jsonl"
            try:
                events = (
                    JsonlTranscriptStore(transcript_path).read_all()
                    if transcript_path.exists()
                    else ()
                )
            except (OSError, ValidationError, ValueError):
                events = ()

            sessions.append(
                ConsoleSessionListItem(
                    session_id=checkpoint.session_id,
                    incident_id=checkpoint.incident_id,
                    family=_family_from_triage_input(
                        _latest_triage_input_from_events(events)
                    ),
                    current_phase=checkpoint.current_phase,
                    requested_mode=checkpoint.operator_shell.requested_mode,
                    effective_mode=checkpoint.operator_shell.effective_mode,
                    approval_status=checkpoint.approval_state.status,
                    latest_verifier_summary=_latest_verifier_summary_from_events(events),
                    last_updated=checkpoint.latest_checkpoint_time,
                )
            )

        sessions.sort(
            key=lambda summary: (summary.last_updated, summary.session_id),
            reverse=True,
        )
        if limit is not None:
            sessions = sessions[:limit]
        return ConsoleSessionsResponse(sessions=sessions)

    def get_session_detail(self, session_id: str) -> ConsoleSessionDetail:
        context = self._load_context(session_id)
        status_payload = build_shell_status_payload(context, handoff_root=self.handoff_root)
        handoff = self.get_handoff_artifact(session_id)
        checkpoint = context.checkpoint
        return ConsoleSessionDetail(
            session_id=context.session_id,
            incident_id=checkpoint.incident_id,
            checkpoint_id=checkpoint.checkpoint_id,
            family=str(status_payload["family"]),
            current_phase=checkpoint.current_phase,
            current_step=checkpoint.current_step,
            summary_of_progress=checkpoint.summary_of_progress,
            requested_mode=checkpoint.operator_shell.requested_mode,
            effective_mode=checkpoint.operator_shell.effective_mode,
            mode_reason=checkpoint.operator_shell.mode_reason,
            approval=checkpoint.approval_state,
            pending_verifier=checkpoint.pending_verifier,
            next_recommended_action=str(status_payload["next_action"]),
            current_evidence_summary=str(status_payload["current_evidence_summary"]),
            latest_verifier_summary=str(status_payload["latest_verifier"]),
            latest_checkpoint_time=checkpoint.latest_checkpoint_time,
            handoff=handoff,
        )

    def get_session_timeline(
        self,
        session_id: str,
        *,
        limit: int = 20,
    ) -> ConsoleSessionTimelineResponse:
        if limit < 1:
            msg = "limit must be greater than zero"
            raise ValueError(msg)
        context = self._load_context(session_id)
        filtered_events = _timeline_events(context.transcript_events, limit=limit)
        entries = [_timeline_entry(event) for event in filtered_events]
        return ConsoleSessionTimelineResponse(
            session_id=context.session_id,
            incident_id=context.checkpoint.incident_id,
            entries=entries,
        )

    def resolve_approval(
        self,
        session_id: str,
        *,
        decision: ConsoleApprovalDecision,
        reason: str | None = None,
    ) -> ConsoleApprovalActionResponse:
        run_resolve_deployment_regression_approval(
            session_id=session_id,
            decision=decision.value,
            reason=reason,
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
        )
        return ConsoleApprovalActionResponse(
            approval_decision=decision,
            session=self.get_session_detail(session_id),
            verification=self.get_verification_result(session_id),
        )

    def get_verification_result(self, session_id: str) -> ConsoleVerificationResult:
        context = self._load_context(session_id)
        record = context.latest_outcome_verification_output()
        resolution = context.latest_verified_outcome_verification_output()

        if resolution.is_available and resolution.artifact is not None:
            return ConsoleVerificationResult(
                session_id=context.session_id,
                incident_id=context.checkpoint.incident_id,
                current_phase=context.checkpoint.current_phase,
                status=ConsoleVerificationStatus.VERIFIED,
                verifier_status=record.verifier_status,
                summary=resolution.artifact.summary,
                output=resolution.artifact,
            )

        if resolution.is_failure:
            reason = resolution.reason or "Outcome verification failed."
            return ConsoleVerificationResult(
                session_id=context.session_id,
                incident_id=context.checkpoint.incident_id,
                current_phase=context.checkpoint.current_phase,
                status=ConsoleVerificationStatus.FAILED,
                verifier_status=record.verifier_status,
                summary=reason,
                failure_reason=reason,
            )

        reason = (
            resolution.reason
            or "No verifier-passed outcome verification artifact has been recorded yet."
        )
        return ConsoleVerificationResult(
            session_id=context.session_id,
            incident_id=context.checkpoint.incident_id,
            current_phase=context.checkpoint.current_phase,
            status=ConsoleVerificationStatus.INSUFFICIENT,
            verifier_status=record.verifier_status,
            summary=reason,
            insufficiency_reason=reason,
        )

    def rerun_verification(self, session_id: str) -> ConsoleVerificationActionResponse:
        run_verify_deployment_regression_outcome(
            session_id=session_id,
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
        )
        return ConsoleVerificationActionResponse(
            session=self.get_session_detail(session_id),
            verification=self.get_verification_result(session_id),
        )

    def get_handoff_artifact(self, session_id: str) -> ConsoleHandoffAccess:
        context = self._load_context(session_id)
        store = JsonIncidentHandoffArtifactStore.for_incident(
            context.checkpoint.incident_id,
            root=self.handoff_root,
        )
        artifact = store.load_optional()
        return ConsoleHandoffAccess(
            available=artifact is not None,
            handoff_path=store.path,
            artifact=artifact,
        )

    def export_handoff_artifact(self, session_id: str) -> ConsoleHandoffExportResponse:
        result = IncidentHandoffArtifactRegenerator(
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            working_memory_root=self.working_memory_root,
            handoff_root=self.handoff_root,
        ).regenerate(session_id)

        artifact = None
        if result.incident_id is not None:
            artifact = JsonIncidentHandoffArtifactStore.for_incident(
                result.incident_id,
                root=self.handoff_root,
            ).load_optional()

        return ConsoleHandoffExportResponse(result=result, artifact=artifact)

    def _load_context(self, session_id: str) -> SessionArtifactContext:
        return load_artifact_context(
            session_id,
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            working_memory_root=self.working_memory_root,
        )
