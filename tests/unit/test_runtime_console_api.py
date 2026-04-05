from datetime import UTC, datetime
from pathlib import Path

from memory.checkpoints import (
    ApprovalState,
    ApprovalStatus,
    JsonCheckpointStore,
    OperatorAutonomyMode,
    OperatorShellState,
    SessionCheckpoint,
)
from permissions.models import (
    EvaluatedActionType,
    PermissionAction,
    PermissionActionCategory,
    PermissionDecision,
    PermissionDecisionProvenance,
    PermissionPolicySource,
    PermissionSafetyBoundary,
)
from runtime.console_api import ConsoleTimelineKind, OperatorConsoleAPI
from tools.models import ToolCall, ToolResult, ToolResultStatus, ToolRiskLevel
from transcripts.models import (
    ApprovalResolvedEvent,
    CheckpointWrittenEvent,
    PermissionDecisionEvent,
    ResumeStartedEvent,
    ToolRequestEvent,
    ToolResultEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus


def _write_checkpoint(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
    current_phase: str,
    latest_checkpoint_time: datetime,
    approval_state: ApprovalState | None = None,
    operator_shell: OperatorShellState | None = None,
    summary_of_progress: str = "Console API checkpoint.",
) -> None:
    JsonCheckpointStore(tmp_path / "checkpoints" / f"{session_id}.json").write(
        SessionCheckpoint(
            checkpoint_id=f"{session_id}-checkpoint",
            session_id=session_id,
            incident_id=incident_id,
            current_phase=current_phase,
            current_step=6,
            selected_skills=["incident-triage"],
            approval_state=approval_state or ApprovalState(status=ApprovalStatus.NONE),
            operator_shell=operator_shell or OperatorShellState(),
            latest_checkpoint_time=latest_checkpoint_time,
            summary_of_progress=summary_of_progress,
        )
    )


def _append_events(tmp_path: Path, *, session_id: str, events: list[object]) -> None:
    store = JsonlTranscriptStore(tmp_path / "transcripts" / f"{session_id}.jsonl")
    for event in events:
        store.append(event)


def _triage_request_event(
    *,
    session_id: str,
    step_index: int = 1,
) -> ToolRequestEvent:
    return ToolRequestEvent(
        session_id=session_id,
        step_index=step_index,
        call_id=f"{session_id}-triage",
        tool_call=ToolCall(
            name="incident_payload_summary",
            arguments={
                "incident_id": f"incident-for-{session_id}",
                "title": "payments-api unhealthy after deploy",
                "service": "payments-api",
                "symptoms": ["health endpoint degraded"],
                "impact_summary": "Checkout traffic is degraded.",
                "service_base_url": "http://127.0.0.1:8001",
                "expected_bad_version": "2.1.0",
                "expected_previous_version": "2.0.9",
            },
        ),
    )


def _verifier_event(
    *,
    session_id: str,
    verifier_name: str,
    summary: str,
    step_index: int = 2,
) -> VerifierResultEvent:
    return VerifierResultEvent(
        session_id=session_id,
        step_index=step_index,
        verifier_name=verifier_name,
        request=VerifierRequest(name=verifier_name, target=session_id),
        result=VerifierResult(status=VerifierStatus.PASS, summary=summary),
    )


def test_console_api_lists_sessions_and_builds_detail_and_timeline(tmp_path: Path) -> None:
    older_time = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    newer_time = datetime(2026, 4, 5, 12, 5, tzinfo=UTC)

    _write_checkpoint(
        tmp_path,
        session_id="session-older",
        incident_id="incident-older",
        current_phase="recommendation_supported",
        latest_checkpoint_time=older_time,
    )
    _append_events(
        tmp_path,
        session_id="session-older",
        events=[
            _triage_request_event(session_id="session-older"),
            _verifier_event(
                session_id="session-older",
                verifier_name="incident_recommendation_outcome",
                summary="Rollback-readiness recommendation is supported.",
            ),
        ],
    )

    _write_checkpoint(
        tmp_path,
        session_id="session-newer",
        incident_id="incident-newer",
        current_phase="action_stub_pending_approval",
        latest_checkpoint_time=newer_time,
        approval_state=ApprovalState(
            status=ApprovalStatus.PENDING,
            requested_action="rollback_recent_deployment_candidate",
            reason="Operator review required.",
        ),
        operator_shell=OperatorShellState(
            requested_mode=OperatorAutonomyMode.AUTO_SAFE,
            effective_mode=OperatorAutonomyMode.SEMI_AUTO,
            mode_reason="target is not allowlisted",
        ),
        summary_of_progress="Rollback candidate is pending approval.",
    )
    _append_events(
        tmp_path,
        session_id="session-newer",
        events=[
            _triage_request_event(session_id="session-newer"),
            ResumeStartedEvent(
                session_id="session-newer",
                step_index=1,
                checkpoint_id="session-newer-checkpoint",
                reason="Resuming action-stub step.",
            ),
                _verifier_event(
                    session_id="session-newer",
                    verifier_name="incident_action_stub_outcome",
                    summary="Rollback candidate is pending operator approval.",
                    step_index=6,
                ),
            PermissionDecisionEvent(
                session_id="session-newer",
                step_index=7,
                decision=PermissionDecision(
                    tool_name="deployment_rollback_executor",
                    risk_level=ToolRiskLevel.WRITE,
                    action=PermissionAction.ASK,
                    reason=(
                        "approval was already recorded for the reviewed rollback scope"
                    ),
                    provenance=PermissionDecisionProvenance(
                        policy_source=PermissionPolicySource.DEFAULT_SAFE_TOOL_RISK,
                        action_category=PermissionActionCategory.TOOL_EXECUTION,
                        evaluated_action_type=EvaluatedActionType.WRITE_TOOL,
                        approval_required=True,
                        approval_reason="approval was already recorded",
                        safety_boundary=PermissionSafetyBoundary.HUMAN_APPROVAL_REQUIRED,
                        notes=["not a fresh request for approval"],
                    ),
                ),
            ),
            ToolRequestEvent(
                session_id="session-newer",
                step_index=7,
                call_id="rollback-call",
                tool_call=ToolCall(
                    name="deployment_rollback_executor",
                    arguments={},
                ),
            ),
            ToolResultEvent(
                session_id="session-newer",
                step_index=7,
                call_id="rollback-call",
                tool_name="deployment_rollback_executor",
                result=ToolResult(status=ToolResultStatus.SUCCEEDED, output={}),
            ),
            ApprovalResolvedEvent(
                session_id="session-newer",
                step_index=7,
                decision="approved",
                requested_action="rollback_recent_deployment_candidate",
                reason="Approved by operator.",
            ),
            CheckpointWrittenEvent(
                session_id="session-newer",
                step_index=7,
                checkpoint_id="session-newer-checkpoint-2",
                checkpoint_path=tmp_path / "checkpoints" / "session-newer.json",
                summary_of_progress="Approval approved for rollback_recent_deployment_candidate.",
            ),
        ],
    )

    api = OperatorConsoleAPI(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    )

    sessions = api.list_sessions()

    assert [session.session_id for session in sessions.sessions] == [
        "session-newer",
        "session-older",
    ]
    assert sessions.sessions[0].family == "deployment-regression"
    assert sessions.sessions[0].requested_mode is OperatorAutonomyMode.AUTO_SAFE
    assert sessions.sessions[0].effective_mode is OperatorAutonomyMode.SEMI_AUTO
    assert sessions.sessions[0].approval_status is ApprovalStatus.PENDING
    assert (
        sessions.sessions[0].latest_verifier_summary
        == "incident_action_stub_outcome=pass: Rollback candidate is pending operator approval."
    )

    detail = api.get_session_detail("session-newer")

    assert detail.session_id == "session-newer"
    assert detail.incident_id == "incident-newer"
    assert detail.family == "deployment-regression"
    assert detail.current_phase == "action_stub_pending_approval"
    assert detail.requested_mode is OperatorAutonomyMode.AUTO_SAFE
    assert detail.effective_mode is OperatorAutonomyMode.SEMI_AUTO
    assert detail.mode_reason == "target is not allowlisted"
    assert detail.approval.status is ApprovalStatus.PENDING
    assert (
        detail.next_recommended_action
        == "Review the rollback candidate and run /approve or /deny."
    )
    assert detail.handoff.available is False

    timeline = api.get_session_timeline("session-newer", limit=10)

    assert [entry.kind for entry in timeline.entries] == [
        ConsoleTimelineKind.RESUME,
        ConsoleTimelineKind.VERIFIER,
        ConsoleTimelineKind.PERMISSION,
        ConsoleTimelineKind.EXECUTION,
        ConsoleTimelineKind.EXECUTION,
        ConsoleTimelineKind.APPROVAL,
        ConsoleTimelineKind.CHECKPOINT,
    ]
    assert timeline.entries[2].tool_name is None
    assert timeline.entries[3].tool_name == "deployment_rollback_executor"
    assert timeline.entries[-1].checkpoint_id == "session-newer-checkpoint-2"
