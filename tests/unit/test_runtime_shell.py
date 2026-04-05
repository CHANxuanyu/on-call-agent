from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest

from memory.checkpoints import (
    ApprovalState,
    ApprovalStatus,
    JsonCheckpointStore,
    OperatorAutonomyMode,
    OperatorShellState,
    SessionCheckpoint,
)
from runtime.shell import AutoSafeGateResult, OperatorShell
from tools.models import ToolCall
from transcripts.models import (
    ApprovalResolvedEvent,
    CheckpointWrittenEvent,
    ToolRequestEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus


def _write_settings(
    path: Path,
    *,
    enabled: bool,
    allowed_base_urls: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    allowed_lines = ", ".join(f'"{base_url}"' for base_url in allowed_base_urls)
    path.write_text(
        "\n".join(
            [
                "[shell]",
                'default_mode = "manual"',
                "",
                "[autonomy.auto_safe]",
                f"enabled = {'true' if enabled else 'false'}",
                f"allowed_base_urls = [{allowed_lines}]",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_session_checkpoint(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
    current_phase: str,
    approval_state: ApprovalState | None = None,
    operator_shell: OperatorShellState | None = None,
    latest_checkpoint_time: datetime | None = None,
    summary_of_progress: str = "Stable checkpoint for shell tests.",
) -> None:
    checkpoint_root = tmp_path / "checkpoints"
    transcript_root = tmp_path / "transcripts"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    transcript_root.mkdir(parents=True, exist_ok=True)
    JsonCheckpointStore(checkpoint_root / f"{session_id}.json").write(
        SessionCheckpoint(
            checkpoint_id=f"{session_id}-checkpoint",
            session_id=session_id,
            incident_id=incident_id,
            current_phase=current_phase,
            current_step=6,
            selected_skills=["incident-triage"],
            approval_state=approval_state or ApprovalState(status=ApprovalStatus.NONE),
            operator_shell=operator_shell or OperatorShellState(),
            latest_checkpoint_time=latest_checkpoint_time
            or datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
            summary_of_progress=summary_of_progress,
        )
    )
    (transcript_root / f"{session_id}.jsonl").write_text("", encoding="utf-8")


def _append_transcript_events(
    tmp_path: Path,
    *,
    session_id: str,
    events: list[object],
) -> None:
    store = JsonlTranscriptStore(tmp_path / "transcripts" / f"{session_id}.jsonl")
    for event in events:
        store.append(event)


def _deployment_triage_request_event(
    *,
    session_id: str,
    step_index: int = 1,
    base_url: str = "http://127.0.0.1:8001",
) -> ToolRequestEvent:
    return ToolRequestEvent(
        session_id=session_id,
        step_index=step_index,
        call_id=f"{session_id}-triage-call",
        tool_call=ToolCall(
            name="incident_payload_summary",
            arguments={
                "incident_id": f"incident-for-{session_id}",
                "title": "payments-api unhealthy after deploy",
                "service": "payments-api",
                "symptoms": ["health endpoint is degraded"],
                "impact_summary": "Checkout traffic is degraded.",
                "service_base_url": base_url,
                "expected_bad_version": "2.1.0",
                "expected_previous_version": "2.0.9",
            },
        ),
    )


def _verifier_result_event(
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


def test_mode_command_persists_operator_shell_state(tmp_path: Path) -> None:
    session_id = "session-shell-mode"
    _write_session_checkpoint(
        tmp_path,
        session_id=session_id,
        incident_id="incident-shell-mode",
        current_phase="recommendation_supported",
    )

    stdout = StringIO()
    stderr = StringIO()
    shell = OperatorShell(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
        settings_path=tmp_path / "missing-settings.toml",
        stdout=stdout,
        stderr=stderr,
    )
    shell.current_session_id = session_id

    should_exit = shell.handle_line("/mode semi-auto")

    assert should_exit is False
    checkpoint = JsonCheckpointStore(
        tmp_path / "checkpoints" / f"{session_id}.json"
    ).load()
    assert checkpoint.operator_shell.requested_mode is OperatorAutonomyMode.SEMI_AUTO
    assert checkpoint.operator_shell.effective_mode is OperatorAutonomyMode.SEMI_AUTO
    assert checkpoint.operator_shell.mode_reason is None
    events = JsonlTranscriptStore(tmp_path / "transcripts" / f"{session_id}.jsonl").read_all()
    assert isinstance(events[-1], CheckpointWrittenEvent)
    assert "requested=semi-auto, effective=semi-auto" in events[-1].summary_of_progress
    assert stderr.getvalue() == ""


def test_auto_safe_downgrade_is_persisted_durably(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "session-shell-auto-safe"
    _write_session_checkpoint(
        tmp_path,
        session_id=session_id,
        incident_id="incident-shell-auto-safe",
        current_phase="action_stub_pending_approval",
        approval_state=ApprovalState(
            status=ApprovalStatus.PENDING,
            requested_action="rollback_recent_deployment_candidate",
            reason="Pending review",
        ),
    )

    stdout = StringIO()
    stderr = StringIO()
    shell = OperatorShell(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
        settings_path=tmp_path / "missing-settings.toml",
        stdout=stdout,
        stderr=stderr,
    )
    shell.current_session_id = session_id
    monkeypatch.setattr(
        OperatorShell,
        "evaluate_auto_safe_gate",
        lambda self, context: AutoSafeGateResult(
            allowed=False,
            reason="test gate refused auto-safe execution",
            checked_conditions=[],
        ),
    )

    should_exit = shell.handle_line("/mode auto-safe")

    assert should_exit is False
    checkpoint = JsonCheckpointStore(
        tmp_path / "checkpoints" / f"{session_id}.json"
    ).load()
    assert checkpoint.operator_shell.requested_mode is OperatorAutonomyMode.AUTO_SAFE
    assert checkpoint.operator_shell.effective_mode is OperatorAutonomyMode.SEMI_AUTO
    assert checkpoint.operator_shell.mode_reason == "test gate refused auto-safe execution"
    assert "auto-safe degraded to semi-auto" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_sessions_lists_recent_checkpoint_backed_sessions(tmp_path: Path) -> None:
    _write_session_checkpoint(
        tmp_path,
        session_id="session-older",
        incident_id="incident-older",
        current_phase="recommendation_supported",
        latest_checkpoint_time=datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
    )
    _append_transcript_events(
        tmp_path,
        session_id="session-older",
        events=[
            _deployment_triage_request_event(session_id="session-older"),
            _verifier_result_event(
                session_id="session-older",
                verifier_name="incident_recommendation_outcome",
                summary="Rollback-readiness recommendation is supported.",
            ),
        ],
    )
    _write_session_checkpoint(
        tmp_path,
        session_id="session-newer",
        incident_id="incident-newer",
        current_phase="action_stub_pending_approval",
        approval_state=ApprovalState(
            status=ApprovalStatus.PENDING,
            requested_action="rollback_recent_deployment_candidate",
        ),
        operator_shell=OperatorShellState(
            requested_mode=OperatorAutonomyMode.AUTO_SAFE,
            effective_mode=OperatorAutonomyMode.SEMI_AUTO,
            mode_reason="target is not allowlisted",
        ),
        latest_checkpoint_time=datetime(2026, 4, 5, 12, 5, tzinfo=UTC),
    )
    _append_transcript_events(
        tmp_path,
        session_id="session-newer",
        events=[
            _deployment_triage_request_event(session_id="session-newer"),
            _verifier_result_event(
                session_id="session-newer",
                verifier_name="incident_action_stub_outcome",
                summary="Rollback candidate is pending operator approval.",
            ),
        ],
    )

    stdout = StringIO()
    stderr = StringIO()
    shell = OperatorShell(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
        settings_path=tmp_path / "missing-settings.toml",
        stdout=stdout,
        stderr=stderr,
    )
    shell.current_session_id = "session-newer"

    should_exit = shell.handle_line("/sessions")

    assert should_exit is False
    output = stdout.getvalue()
    assert "Recent sessions:" in output
    assert "*[1] session-newer" in output
    assert "family=deployment-regression" in output
    assert "mode=auto-safe->semi-auto" in output
    assert "approval=pending" in output
    assert "[2] session-older" in output
    assert stderr.getvalue() == ""


def test_resume_accepts_numeric_sessions_index_and_prints_summary(tmp_path: Path) -> None:
    _write_session_checkpoint(
        tmp_path,
        session_id="session-one",
        incident_id="incident-one",
        current_phase="recommendation_supported",
        latest_checkpoint_time=datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
    )
    _append_transcript_events(
        tmp_path,
        session_id="session-one",
        events=[
            _deployment_triage_request_event(session_id="session-one"),
            _verifier_result_event(
                session_id="session-one",
                verifier_name="incident_recommendation_outcome",
                summary="Recommendation is supported.",
            ),
        ],
    )
    _write_session_checkpoint(
        tmp_path,
        session_id="session-two",
        incident_id="incident-two",
        current_phase="action_stub_pending_approval",
        latest_checkpoint_time=datetime(2026, 4, 5, 12, 1, tzinfo=UTC),
    )
    _append_transcript_events(
        tmp_path,
        session_id="session-two",
        events=[_deployment_triage_request_event(session_id="session-two")],
    )

    stdout = StringIO()
    stderr = StringIO()
    shell = OperatorShell(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
        settings_path=tmp_path / "missing-settings.toml",
        stdout=stdout,
        stderr=stderr,
    )

    should_exit = shell.handle_line("/resume 2")

    assert should_exit is False
    assert shell.current_session_id == "session-one"
    output = stdout.getvalue()
    assert "resumed session [2]: session-one" in output
    assert "session: session-one incident=incident-one family=deployment-regression" in output
    assert "verifier: incident_recommendation_outcome=pass: Recommendation is supported." in output
    assert stderr.getvalue() == ""


def test_status_shows_mode_reason_and_handoff_availability(tmp_path: Path) -> None:
    session_id = "session-status"
    incident_id = "incident-status"
    _write_session_checkpoint(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
        current_phase="action_stub_pending_approval",
        approval_state=ApprovalState(
            status=ApprovalStatus.PENDING,
            requested_action="rollback_recent_deployment_candidate",
        ),
        operator_shell=OperatorShellState(
            requested_mode=OperatorAutonomyMode.AUTO_SAFE,
            effective_mode=OperatorAutonomyMode.SEMI_AUTO,
            mode_reason="target http://127.0.0.1:9999 is not allowlisted",
        ),
        latest_checkpoint_time=datetime(2026, 4, 5, 12, 15, tzinfo=UTC),
        summary_of_progress="Rollback candidate is pending approval.",
    )
    _append_transcript_events(
        tmp_path,
        session_id=session_id,
        events=[
            _deployment_triage_request_event(session_id=session_id),
            _verifier_result_event(
                session_id=session_id,
                verifier_name="incident_action_stub_outcome",
                summary="Rollback candidate is pending operator approval.",
            ),
        ],
    )
    handoff_root = tmp_path / "handoffs"
    handoff_root.mkdir(parents=True, exist_ok=True)
    (handoff_root / f"{incident_id}.json").write_text("{}", encoding="utf-8")

    stdout = StringIO()
    stderr = StringIO()
    shell = OperatorShell(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=handoff_root,
        settings_path=tmp_path / "missing-settings.toml",
        stdout=stdout,
        stderr=stderr,
    )
    shell.current_session_id = session_id

    should_exit = shell.handle_line("/status")

    assert should_exit is False
    output = stdout.getvalue()
    assert "mode: requested=auto-safe effective=semi-auto" in output
    assert "downgrade_reason: target http://127.0.0.1:9999 is not allowlisted" in output
    assert "approval: pending (rollback_recent_deployment_candidate)" in output
    assert "handoff: available at" in output
    assert "updated: 2026-04-05T12:15:00+00:00" in output
    assert stderr.getvalue() == ""


def test_why_not_auto_explains_current_mode_and_gate_failures(tmp_path: Path) -> None:
    session_id = "session-why-not-auto"
    settings_path = tmp_path / ".oncall" / "settings.toml"
    _write_settings(settings_path, enabled=False, allowed_base_urls=[])
    _write_session_checkpoint(
        tmp_path,
        session_id=session_id,
        incident_id="incident-why-not-auto",
        current_phase="action_stub_pending_approval",
        approval_state=ApprovalState(
            status=ApprovalStatus.PENDING,
            requested_action="rollback_recent_deployment_candidate",
        ),
        operator_shell=OperatorShellState(
            requested_mode=OperatorAutonomyMode.AUTO_SAFE,
            effective_mode=OperatorAutonomyMode.SEMI_AUTO,
            mode_reason="auto-safe execution is disabled in the runtime settings",
        ),
        latest_checkpoint_time=datetime(2026, 4, 5, 12, 20, tzinfo=UTC),
    )
    _append_transcript_events(
        tmp_path,
        session_id=session_id,
        events=[_deployment_triage_request_event(session_id=session_id)],
    )

    stdout = StringIO()
    stderr = StringIO()
    shell = OperatorShell(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
        settings_path=settings_path,
        stdout=stdout,
        stderr=stderr,
    )
    shell.current_session_id = session_id

    should_exit = shell.handle_line("/why-not-auto")

    assert should_exit is False
    output = stdout.getvalue()
    assert "mode: requested=auto-safe effective=semi-auto" in output
    assert (
        "downgrade_reason: auto-safe execution is disabled in the runtime settings"
        in output
    )
    assert "target: http://127.0.0.1:8001 allowlisted=no" in output
    assert "auto_safe_qualifies_now: no" in output
    assert (
        "summary: auto-safe execution is disabled in the runtime settings"
        in output
    )
    assert "- fail: auto-safe execution is disabled in the runtime settings" in output
    assert stderr.getvalue() == ""


def test_tail_renders_recent_operator_activity(tmp_path: Path) -> None:
    session_id = "session-tail"
    _write_session_checkpoint(
        tmp_path,
        session_id=session_id,
        incident_id="incident-tail",
        current_phase="outcome_verification_succeeded",
    )
    _append_transcript_events(
        tmp_path,
        session_id=session_id,
        events=[
            CheckpointWrittenEvent(
                session_id=session_id,
                step_index=5,
                timestamp=datetime(2026, 4, 5, 12, 1, tzinfo=UTC),
                checkpoint_id=f"{session_id}-checkpoint-5",
                checkpoint_path=tmp_path / "checkpoints" / f"{session_id}.json",
                summary_of_progress="Rollback candidate is pending approval.",
            ),
            ApprovalResolvedEvent(
                session_id=session_id,
                step_index=6,
                timestamp=datetime(2026, 4, 5, 12, 2, tzinfo=UTC),
                decision="approved",
                requested_action="rollback_recent_deployment_candidate",
                reason="Approved from shell tests.",
            ),
            VerifierResultEvent(
                session_id=session_id,
                step_index=7,
                timestamp=datetime(2026, 4, 5, 12, 3, tzinfo=UTC),
                verifier_name="deployment_outcome_verification",
                request=VerifierRequest(
                    name="deployment_outcome_verification",
                    target=session_id,
                ),
                result=VerifierResult(
                    status=VerifierStatus.PASS,
                    summary="External runtime checks confirmed recovery.",
                ),
            ),
        ],
    )

    stdout = StringIO()
    stderr = StringIO()
    shell = OperatorShell(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
        settings_path=tmp_path / "missing-settings.toml",
        stdout=stdout,
        stderr=stderr,
    )
    shell.current_session_id = session_id

    should_exit = shell.handle_line("/tail --limit 2")

    assert should_exit is False
    output = stdout.getvalue()
    assert "approval approved for rollback_recent_deployment_candidate" in output
    assert "verifier deployment_outcome_verification=pass" in output
    assert "checkpoint: Rollback candidate is pending approval." not in output
    assert stderr.getvalue() == ""
