"""Read-only inspection helpers for durable runtime session state."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from context.handoff_regeneration import (
    HandoffArtifactRegenerationResult,
    HandoffArtifactRegenerationStatus,
)
from context.session_artifacts import (
    ArtifactRecord,
    ArtifactResolution,
    SessionArtifactContext,
)
from transcripts.models import (
    ApprovalResolvedEvent,
    CheckpointWrittenEvent,
    ModelStepEvent,
    PermissionDecisionEvent,
    ResumeStartedEvent,
    ToolRequestEvent,
    ToolResultEvent,
    TranscriptEvent,
    TranscriptEventType,
    VerifierRequestEvent,
    VerifierResultEvent,
)

ArtifactOutputT = TypeVar("ArtifactOutputT", bound=BaseModel)


def load_artifact_context(
    session_id: str,
    *,
    checkpoint_root: Path,
    transcript_root: Path,
    working_memory_root: Path | None,
) -> SessionArtifactContext:
    """Load the durable session state through the existing typed seam."""

    return SessionArtifactContext.load(
        session_id,
        checkpoint_root=checkpoint_root,
        transcript_root=transcript_root,
        working_memory_root=working_memory_root,
    )


def build_session_payload(artifact_context: SessionArtifactContext) -> dict[str, Any]:
    """Build a stable checkpoint-backed session summary payload."""

    checkpoint = artifact_context.checkpoint
    working_memory = artifact_context.latest_incident_working_memory()
    return {
        "session_id": artifact_context.session_id,
        "incident_id": checkpoint.incident_id,
        "checkpoint_id": checkpoint.checkpoint_id,
        "current_phase": checkpoint.current_phase.value,
        "current_step": checkpoint.current_step,
        "summary_of_progress": checkpoint.summary_of_progress,
        "latest_checkpoint_time": checkpoint.latest_checkpoint_time.isoformat(),
        "selected_skills": list(checkpoint.selected_skills),
        "approval_state": checkpoint.approval_state.model_dump(mode="json"),
        "operator_shell": checkpoint.operator_shell.model_dump(mode="json"),
        "pending_verifier": (
            checkpoint.pending_verifier.model_dump(mode="json")
            if checkpoint.pending_verifier is not None
            else None
        ),
        "transcript_event_count": len(artifact_context.transcript_events),
        "working_memory_present": working_memory is not None,
        "checkpoint_path": str(artifact_context.checkpoint_path),
        "transcript_path": str(artifact_context.transcript_path),
        "working_memory_path": str(artifact_context.working_memory_path),
        "reconciliation": artifact_context.reconciliation.model_dump(mode="json"),
    }


def render_session_payload(payload: dict[str, Any]) -> str:
    """Render a compact human-readable session summary."""

    approval_state = payload["approval_state"]
    operator_shell = payload["operator_shell"]
    pending_verifier = payload["pending_verifier"]
    lines = [
        f"session_id: {payload['session_id']}",
        f"incident_id: {payload['incident_id']}",
        f"checkpoint_id: {payload['checkpoint_id']}",
        f"current_phase: {payload['current_phase']}",
        f"current_step: {payload['current_step']}",
        f"summary_of_progress: {payload['summary_of_progress']}",
        f"latest_checkpoint_time: {payload['latest_checkpoint_time']}",
        f"selected_skills: {', '.join(payload['selected_skills']) or 'none'}",
        f"approval_status: {approval_state['status']}",
        "operator_mode: "
        f"requested={operator_shell['requested_mode']} "
        f"effective={operator_shell['effective_mode']}",
        f"pending_verifier: "
        f"{pending_verifier['verifier_name'] if pending_verifier is not None else 'none'}",
        f"transcript_event_count: {payload['transcript_event_count']}",
        f"working_memory_present: {payload['working_memory_present']}",
        f"checkpoint_path: {payload['checkpoint_path']}",
        f"transcript_path: {payload['transcript_path']}",
        f"working_memory_path: {payload['working_memory_path']}",
        (
            "reconciliation_tail: "
            f"{payload['reconciliation']['tail']['classification']} "
            f"({payload['reconciliation']['tail']['event_count']} events)"
        ),
    ]
    if operator_shell["mode_reason"] is not None:
        lines.insert(9, f"operator_mode_reason: {operator_shell['mode_reason']}")
    return "\n".join(lines)


def build_artifact_payload(artifact_context: SessionArtifactContext) -> dict[str, Any]:
    """Build an ordered artifact-chain payload using current runtime semantics."""

    stages: list[dict[str, Any]] = []
    for name, record_loader, resolution_loader in _artifact_stage_loaders():
        record = record_loader(artifact_context)
        resolution = resolution_loader(artifact_context)
        stages.append(
            {
                "stage": name,
                "tool_name": record.tool_name,
                "verifier_name": record.verifier_name,
                "latest_record": _record_payload(record),
                "verified_resolution": _resolution_payload(resolution),
            }
        )

    return {
        "session_id": artifact_context.session_id,
        "incident_id": artifact_context.checkpoint.incident_id,
        "current_phase": artifact_context.checkpoint.current_phase.value,
        "reconciliation": artifact_context.reconciliation.model_dump(mode="json"),
        "stages": stages,
    }


def render_artifact_payload(payload: dict[str, Any]) -> str:
    """Render a compact artifact-chain summary."""

    lines = [
        f"session_id: {payload['session_id']}",
        f"incident_id: {payload['incident_id']}",
        f"current_phase: {payload['current_phase']}",
    ]
    for stage in payload["stages"]:
        record = stage["latest_record"]
        resolution = stage["verified_resolution"]
        state = "recorded"
        detail = ""
        if resolution["is_available"]:
            state = "verified"
            detail = "artifact available"
        elif resolution["is_failure"]:
            state = "failure"
            detail = resolution["reason"] or "runtime reported a synthetic failure"
        elif resolution["is_insufficient"]:
            state = "insufficient"
            detail = resolution["reason"] or "artifact is unavailable"
        elif record["invalid_output_detail"] is not None:
            state = "invalid_output"
            detail = record["invalid_output_detail"]
        elif record["has_output"]:
            state = "unverified"
            detail = "output exists but does not have a verifier-passed record"
        elif record["synthetic_failure"] is not None:
            state = "failure"
            detail = record["synthetic_failure"]["reason"]
        else:
            detail = "no structured output recorded"

        verifier_status = record["verifier_status"] or "missing"
        line = (
            f"{stage['stage']}: {state} "
            f"(verifier_status={verifier_status}, tool={stage['tool_name']}, "
            f"verifier={stage['verifier_name']})"
        )
        if detail:
            line = f"{line} - {detail}"
        lines.append(line)
    return "\n".join(lines)


def filter_audit_events(
    artifact_context: SessionArtifactContext,
    *,
    limit: int | None,
    event_type: TranscriptEventType | None,
) -> tuple[TranscriptEvent, ...]:
    """Return transcript events filtered through the current event vocabulary."""

    events = artifact_context.transcript_events
    if event_type is not None:
        events = tuple(
            event for event in events if event.event_type == event_type.value
        )
    if limit is not None:
        events = events[-limit:]
    return events


def build_audit_payload(
    artifact_context: SessionArtifactContext,
    *,
    events: tuple[TranscriptEvent, ...],
    limit: int | None,
    event_type: TranscriptEventType | None,
) -> dict[str, Any]:
    """Build a structured audit payload for JSON rendering."""

    return {
        "session_id": artifact_context.session_id,
        "incident_id": artifact_context.checkpoint.incident_id,
        "applied_filters": {
            "limit": limit,
            "event_type": event_type.value if event_type is not None else None,
        },
        "event_count": len(events),
        "events": [build_audit_event_payload(event) for event in events],
    }


def build_audit_event_payload(event: TranscriptEvent) -> dict[str, Any]:
    """Return one audit event payload with the typed event body preserved."""

    payload = event.model_dump(mode="json")
    payload["summary"] = _audit_event_summary(event)
    return payload


def render_audit_events(events: tuple[TranscriptEvent, ...]) -> str:
    """Render compact human-readable audit trail lines."""

    lines = []
    for event in events:
        timestamp = event.timestamp.isoformat()
        step_index = event.step_index if event.step_index is not None else "n/a"
        lines.append(
            f"{timestamp} step={step_index} {event.event_type}: {_audit_event_summary(event)}"
        )
    return "\n".join(lines)


def build_export_payload(
    result: HandoffArtifactRegenerationResult,
) -> dict[str, Any]:
    """Build a JSON-safe handoff export result payload."""

    return result.model_dump(mode="json")


def render_export_payload(payload: dict[str, Any]) -> str:
    """Render a compact export result summary."""

    lines = [
        f"session_id: {payload['session_id']}",
        f"incident_id: {payload['incident_id'] or 'unavailable'}",
        f"status: {payload['status']}",
        f"checkpoint_path: {payload['checkpoint_path']}",
        f"transcript_path: {payload['transcript_path']}",
        f"working_memory_path: {payload['working_memory_path'] or 'unavailable'}",
        f"handoff_path: {payload['handoff_path'] or 'unavailable'}",
    ]
    if payload["status"] == HandoffArtifactRegenerationStatus.WRITTEN.value:
        lines.append(f"used_working_memory: {payload['used_working_memory']}")
        lines.append(f"overwritten_existing: {payload['overwritten_existing']}")
    if payload["required_artifact"] is not None:
        lines.append(f"required_artifact: {payload['required_artifact']}")
    if payload["insufficiency_reason"] is not None:
        lines.append(f"insufficiency_reason: {payload['insufficiency_reason']}")
    if payload["artifact_failure"] is not None:
        lines.append(f"failure_reason: {payload['artifact_failure']['reason']}")
    return "\n".join(lines)


def _artifact_stage_loaders() -> tuple[
    tuple[
        str,
        Callable[[SessionArtifactContext], ArtifactRecord[Any]],
        Callable[[SessionArtifactContext], ArtifactResolution[Any]],
    ],
    ...,
]:
    return (
        (
            "triage",
            SessionArtifactContext.latest_triage_output,
            SessionArtifactContext.latest_verified_triage_output,
        ),
        (
            "follow_up",
            SessionArtifactContext.latest_follow_up_output,
            SessionArtifactContext.latest_verified_follow_up_output,
        ),
        (
            "evidence",
            SessionArtifactContext.latest_evidence_output,
            SessionArtifactContext.latest_verified_evidence_output,
        ),
        (
            "hypothesis",
            SessionArtifactContext.latest_hypothesis_output,
            SessionArtifactContext.latest_verified_hypothesis_output,
        ),
        (
            "recommendation",
            SessionArtifactContext.latest_recommendation_output,
            SessionArtifactContext.latest_verified_recommendation_output,
        ),
        (
            "action_stub",
            SessionArtifactContext.latest_action_stub_output,
            SessionArtifactContext.latest_verified_action_stub_output,
        ),
        (
            "action_execution",
            SessionArtifactContext.latest_action_execution_output,
            SessionArtifactContext.latest_verified_action_execution_output,
        ),
        (
            "outcome_verification",
            SessionArtifactContext.latest_outcome_verification_output,
            SessionArtifactContext.latest_verified_outcome_verification_output,
        ),
    )


def _record_payload(record: ArtifactRecord[ArtifactOutputT]) -> dict[str, Any]:
    return {
        "has_output": record.has_output,
        "is_verified": record.is_verified,
        "verifier_status": (
            record.verifier_status.value if record.verifier_status is not None else None
        ),
        "invalid_output_detail": record.invalid_output_detail,
        "synthetic_failure": _jsonable(record.synthetic_failure),
        "output": _jsonable(record.output),
        "lineage": _jsonable(record.lineage),
    }


def _resolution_payload(
    resolution: ArtifactResolution[ArtifactOutputT],
) -> dict[str, Any]:
    return {
        "is_available": resolution.is_available,
        "is_success": resolution.is_success,
        "is_insufficient": resolution.is_insufficient,
        "is_failure": resolution.is_failure,
        "reason": resolution.reason,
        "artifact": _jsonable(resolution.artifact),
        "insufficiency": _jsonable(resolution.insufficiency),
        "failure": _jsonable(resolution.failure),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _audit_event_summary(event: TranscriptEvent) -> str:
    if isinstance(event, ModelStepEvent):
        return event.summary
    if isinstance(event, ToolRequestEvent):
        return f"requested tool {event.tool_call.name}"
    if isinstance(event, ToolResultEvent):
        return f"tool {event.tool_name} returned {event.result.status.value}"
    if isinstance(event, PermissionDecisionEvent):
        if event.decision.action.value == "ask":
            return (
                f"permission ask for {event.decision.tool_name}: "
                f"{event.decision.reason}"
            )
        return (
            f"permission {event.decision.action.value} for {event.decision.tool_name}"
        )
    if isinstance(event, VerifierRequestEvent):
        return f"requested verifier {event.verifier_name}"
    if isinstance(event, VerifierResultEvent):
        return (
            f"verifier {event.verifier_name} returned {event.result.status.value}"
        )
    if isinstance(event, CheckpointWrittenEvent):
        return f"wrote checkpoint {event.checkpoint_id}"
    if isinstance(event, ResumeStartedEvent):
        return f"resumed from checkpoint {event.checkpoint_id}: {event.reason}"
    if isinstance(event, ApprovalResolvedEvent):
        return (
            f"approval {event.decision} for {event.requested_action}"
            + (f": {event.reason}" if event.reason is not None else "")
        )
    return event.event_type
