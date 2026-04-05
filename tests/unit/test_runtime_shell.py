from io import StringIO
from pathlib import Path

import pytest

from memory.checkpoints import (
    ApprovalState,
    ApprovalStatus,
    JsonCheckpointStore,
    OperatorAutonomyMode,
    SessionCheckpoint,
)
from runtime.shell import AutoSafeGateResult, OperatorShell
from transcripts.models import CheckpointWrittenEvent
from transcripts.writer import JsonlTranscriptStore


def _write_session_checkpoint(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
    current_phase: str,
    approval_state: ApprovalState | None = None,
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
            summary_of_progress="Stable checkpoint for shell tests.",
        )
    )
    (transcript_root / f"{session_id}.jsonl").write_text("", encoding="utf-8")


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
