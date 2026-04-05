import json
import socket
from io import StringIO
from pathlib import Path

import httpx
import pytest

from memory.checkpoints import ApprovalStatus, JsonCheckpointStore, OperatorAutonomyMode
from runtime.demo_target import DemoDeploymentTargetServer
from runtime.shell import OperatorShell


def _can_bind_local_socket() -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
    except OSError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _can_bind_local_socket(),
    reason="local TCP bind is unavailable in the current sandbox",
)


def _write_live_payload(
    tmp_path: Path,
    *,
    incident_id: str,
    session_id: str | None,
    base_url: str,
    expected_bad_version: str,
    expected_previous_version: str,
) -> Path:
    payload: dict[str, object] = {
        "incident_id": incident_id,
        "title": "payments-api unhealthy after the latest deployment",
        "service": "payments-api",
        "symptoms": [
            "health endpoint is degraded",
            "timeouts increased after the rollout",
        ],
        "impact_summary": "Checkout requests are failing after the latest release.",
        "service_base_url": base_url,
        "expected_bad_version": expected_bad_version,
        "expected_previous_version": expected_previous_version,
        "runbook_reference": "runbooks/payments-api",
        "ownership_team": "payments-oncall",
    }
    if session_id is not None:
        payload["session_id"] = session_id

    payload_path = tmp_path / f"{incident_id}.json"
    payload_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return payload_path


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


def _scripted_input(commands: list[str]):
    values = iter(commands)

    def _reader(_: str) -> str:
        try:
            return next(values)
        except StopIteration as exc:  # pragma: no cover
            raise EOFError from exc

    return _reader


def test_shell_semi_auto_runs_end_to_end(tmp_path: Path) -> None:
    with DemoDeploymentTargetServer(port=0) as server:
        payload_session_id = "session-shell-semi-auto"
        payload_path = _write_live_payload(
            tmp_path,
            incident_id="incident-shell-semi-auto",
            session_id=payload_session_id,
            base_url=server.base_url,
            expected_bad_version=server.bad_version,
            expected_previous_version=server.previous_version,
        )
        settings_path = tmp_path / ".oncall" / "settings.toml"
        _write_settings(
            settings_path,
            enabled=False,
            allowed_base_urls=[server.base_url],
        )

        stdout = StringIO()
        stderr = StringIO()
        shell = OperatorShell(
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
            handoff_root=tmp_path / "handoffs",
            settings_path=settings_path,
            input_func=_scripted_input(
                [
                    "/mode semi-auto",
                    f"/new {payload_path}",
                    "/approve Shell-approved rollback.",
                    "/handoff",
                    "/exit",
                ]
            ),
            stdout=stdout,
            stderr=stderr,
        )

        exit_code = shell.run()

        assert exit_code == 0
        assert shell.current_session_id is not None
        assert shell.current_session_id != payload_session_id
        checkpoint = JsonCheckpointStore(
            tmp_path / "checkpoints" / f"{shell.current_session_id}.json"
        ).load()
        assert checkpoint.current_phase == "outcome_verification_succeeded"
        assert checkpoint.approval_state.status is ApprovalStatus.APPROVED
        assert checkpoint.operator_shell.effective_mode is OperatorAutonomyMode.SEMI_AUTO
        assert (tmp_path / "handoffs" / "incident-shell-semi-auto.json").exists()
        assert f"created new session: {shell.current_session_id}" in stdout.getvalue()
        assert "phase: outcome_verification_succeeded" in stdout.getvalue()
        assert stderr.getvalue() == ""


def test_shell_auto_safe_executes_when_allowlisted(tmp_path: Path) -> None:
    with DemoDeploymentTargetServer(port=0) as server:
        payload_session_id = "session-shell-auto-safe"
        payload_path = _write_live_payload(
            tmp_path,
            incident_id="incident-shell-auto-safe",
            session_id=payload_session_id,
            base_url=server.base_url,
            expected_bad_version=server.bad_version,
            expected_previous_version=server.previous_version,
        )
        settings_path = tmp_path / ".oncall" / "settings.toml"
        _write_settings(
            settings_path,
            enabled=True,
            allowed_base_urls=[server.base_url],
        )

        stdout = StringIO()
        stderr = StringIO()
        shell = OperatorShell(
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
            handoff_root=tmp_path / "handoffs",
            settings_path=settings_path,
            input_func=_scripted_input(
                [
                    "/mode auto-safe",
                    f"/new {payload_path}",
                    "/exit",
                ]
            ),
            stdout=stdout,
            stderr=stderr,
        )

        exit_code = shell.run()

        assert exit_code == 0
        assert shell.current_session_id is not None
        assert shell.current_session_id != payload_session_id
        checkpoint = JsonCheckpointStore(
            tmp_path / "checkpoints" / f"{shell.current_session_id}.json"
        ).load()
        assert checkpoint.current_phase == "outcome_verification_succeeded"
        assert checkpoint.approval_state.status is ApprovalStatus.APPROVED
        assert checkpoint.operator_shell.effective_mode is OperatorAutonomyMode.AUTO_SAFE
        assert "auto-safe approved and executed the bounded rollback." in stdout.getvalue()
        assert stderr.getvalue() == ""


def test_shell_auto_safe_degrades_when_target_is_not_allowlisted(tmp_path: Path) -> None:
    with DemoDeploymentTargetServer(port=0) as server:
        payload_session_id = "session-shell-auto-safe-blocked"
        payload_path = _write_live_payload(
            tmp_path,
            incident_id="incident-shell-auto-safe-blocked",
            session_id=payload_session_id,
            base_url=server.base_url,
            expected_bad_version=server.bad_version,
            expected_previous_version=server.previous_version,
        )
        settings_path = tmp_path / ".oncall" / "settings.toml"
        _write_settings(
            settings_path,
            enabled=True,
            allowed_base_urls=["http://127.0.0.1:9999"],
        )

        stdout = StringIO()
        stderr = StringIO()
        shell = OperatorShell(
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
            handoff_root=tmp_path / "handoffs",
            settings_path=settings_path,
            input_func=_scripted_input(
                [
                    "/mode auto-safe",
                    f"/new {payload_path}",
                    "/exit",
                ]
            ),
            stdout=stdout,
            stderr=stderr,
        )

        exit_code = shell.run()

        assert exit_code == 0
        assert shell.current_session_id is not None
        assert shell.current_session_id != payload_session_id
        checkpoint = JsonCheckpointStore(
            tmp_path / "checkpoints" / f"{shell.current_session_id}.json"
        ).load()
        assert checkpoint.current_phase == "action_stub_pending_approval"
        assert checkpoint.approval_state.status is ApprovalStatus.PENDING
        assert checkpoint.operator_shell.requested_mode is OperatorAutonomyMode.AUTO_SAFE
        assert checkpoint.operator_shell.effective_mode is OperatorAutonomyMode.SEMI_AUTO
        assert checkpoint.operator_shell.mode_reason is not None
        assert "not allowlisted" in checkpoint.operator_shell.mode_reason
        assert "auto-safe degraded to semi-auto" in stdout.getvalue()
        assert stderr.getvalue() == ""


def test_shell_new_creates_fresh_session_ids(tmp_path: Path) -> None:
    with DemoDeploymentTargetServer(port=0) as server:
        payload_path = _write_live_payload(
            tmp_path,
            incident_id="incident-shell-repeat-new",
            session_id="session-from-payload",
            base_url=server.base_url,
            expected_bad_version=server.bad_version,
            expected_previous_version=server.previous_version,
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

        assert shell.handle_line(f"/new {payload_path}") is False
        first_session_id = shell.current_session_id
        assert first_session_id is not None
        assert first_session_id != "session-from-payload"

        assert shell.handle_line(f"/new {payload_path}") is False
        second_session_id = shell.current_session_id
        assert second_session_id is not None
        assert second_session_id != "session-from-payload"
        assert second_session_id != first_session_id

        first_checkpoint = JsonCheckpointStore(
            tmp_path / "checkpoints" / f"{first_session_id}.json"
        ).load()
        second_checkpoint = JsonCheckpointStore(
            tmp_path / "checkpoints" / f"{second_session_id}.json"
        ).load()
        assert first_checkpoint.current_phase == "action_stub_pending_approval"
        assert second_checkpoint.current_phase == "action_stub_pending_approval"
        assert stdout.getvalue().count("created new session:") == 2
        assert stderr.getvalue() == ""


def test_shell_new_stops_in_no_action_state_when_service_is_already_healthy(
    tmp_path: Path,
) -> None:
    with DemoDeploymentTargetServer(port=0) as server:
        with httpx.Client(timeout=5.0) as client:
            rollback_response = client.post(f"{server.base_url}/rollback")
            rollback_response.raise_for_status()

        payload_path = _write_live_payload(
            tmp_path,
            incident_id="incident-shell-healthy-no-action",
            session_id="session-shell-healthy-no-action",
            base_url=server.base_url,
            expected_bad_version=server.bad_version,
            expected_previous_version=server.previous_version,
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

        exit_code = shell.handle_line(f"/new {payload_path}")

        assert exit_code is False
        assert shell.current_session_id is not None
        checkpoint = JsonCheckpointStore(
            tmp_path / "checkpoints" / f"{shell.current_session_id}.json"
        ).load()
        assert checkpoint.current_phase == "action_stub_not_actionable"
        assert checkpoint.approval_state.status is ApprovalStatus.NONE
        assert checkpoint.approval_state.reason is not None
        assert "already shows the service healthy" in checkpoint.approval_state.reason
        working_memory = json.loads(
            (
                tmp_path / "working_memory" / "incident-shell-healthy-no-action.json"
            ).read_text(encoding="utf-8")
        )
        assert working_memory["unresolved_gaps"] == []
        assert "already healthy on the known-good version" in working_memory[
            "compact_handoff_note"
        ]
        assert "no rollback candidate is warranted" in stdout.getvalue()
        assert stderr.getvalue() == ""
