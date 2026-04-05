import json
import socket
from pathlib import Path

import httpx
import pytest

from runtime.cli import main
from runtime.demo_target import DemoDeploymentTargetServer


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


def _command_roots(tmp_path: Path) -> list[str]:
    return [
        "--checkpoint-root",
        str(tmp_path / "checkpoints"),
        "--transcript-root",
        str(tmp_path / "transcripts"),
    ]


def _write_live_payload(
    tmp_path: Path,
    *,
    incident_id: str,
    session_id: str,
    base_url: str,
    expected_bad_version: str,
    expected_previous_version: str,
) -> Path:
    payload_path = tmp_path / f"{incident_id}.json"
    payload_path.write_text(
        json.dumps(
            {
                "incident_id": incident_id,
                "session_id": session_id,
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
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return payload_path


@pytest.mark.asyncio
async def test_live_deployment_regression_cli_runs_closed_loop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with DemoDeploymentTargetServer(port=0) as server:
        payload_path = _write_live_payload(
            tmp_path,
            incident_id="incident-live-deployment-1",
            session_id="session-live-deployment-1",
            base_url=server.base_url,
            expected_bad_version=server.bad_version,
            expected_previous_version=server.previous_version,
        )

        exit_code = main(
            [
                "start-incident",
                "--family",
                "deployment-regression",
                "--payload",
                str(payload_path),
                *_command_roots(tmp_path),
                "--json",
            ]
        )
        assert exit_code == 0
        start_payload = json.loads(capsys.readouterr().out)
        session_id = start_payload["session_id"]
        assert session_id == "session-live-deployment-1"
        assert start_payload["current_phase"] == "action_stub_pending_approval"
        assert start_payload["approval_state"]["status"] == "pending"

        exit_code = main(
            [
                "show-audit",
                session_id,
                *_command_roots(tmp_path),
                "--event-type",
                "tool_result",
                "--json",
            ]
        )
        assert exit_code == 0
        audit_payload = json.loads(capsys.readouterr().out)
        evidence_event = next(
            event
            for event in audit_payload["events"]
            if event.get("tool_name") == "evidence_bundle_reader"
        )
        evidence_output = evidence_event["result"]["output"]
        assert f"{server.base_url}/deployment" in evidence_output["evidence_source"]
        assert f"{server.base_url}/health" in evidence_output["evidence_source"]
        assert f"{server.base_url}/metrics" in evidence_output["evidence_source"]
        assert len(evidence_output["observations"]) >= 3

        exit_code = main(
            [
                "resolve-approval",
                session_id,
                "--decision",
                "approve",
                "--reason",
                "Rollback approved for the live demo target.",
                *_command_roots(tmp_path),
                "--json",
            ]
        )
        assert exit_code == 0
        approval_payload = json.loads(capsys.readouterr().out)
        assert approval_payload["approval_state"]["status"] == "approved"
        assert approval_payload["current_phase"] == "outcome_verification_succeeded"

        working_memory_path = tmp_path / "working_memory" / "incident-live-deployment-1.json"
        working_memory_payload = json.loads(working_memory_path.read_text(encoding="utf-8"))
        assert working_memory_payload["source_phase"] == "outcome_verification_succeeded"
        assert (
            working_memory_payload["last_updated_by_step"]
            == "deployment_outcome_verification"
        )
        assert working_memory_payload["unresolved_gaps"] == []
        assert "rollback:2.1.0->2.0.9" in working_memory_payload[
            "important_evidence_references"
        ]
        assert (
            "Outcome verification passed" in working_memory_payload["compact_handoff_note"]
        )

        async with httpx.AsyncClient(timeout=5.0) as client:
            deployment = (await client.get(f"{server.base_url}/deployment")).json()
            health = (await client.get(f"{server.base_url}/health")).json()
        assert deployment["current_version"] == server.previous_version
        assert health["healthy"] is True

        exit_code = main(
            [
                "inspect-artifacts",
                session_id,
                *_command_roots(tmp_path),
                "--json",
            ]
        )
        assert exit_code == 0
        artifact_payload = json.loads(capsys.readouterr().out)
        states = {
            stage["stage"]: stage["verified_resolution"]["is_available"]
            for stage in artifact_payload["stages"]
        }
        assert states["action_execution"] is True
        assert states["outcome_verification"] is True

        exit_code = main(
            [
                "show-audit",
                session_id,
                *_command_roots(tmp_path),
                "--event-type",
                "approval_resolved",
                "--json",
            ]
        )
        assert exit_code == 0
        approval_audit = json.loads(capsys.readouterr().out)
        assert approval_audit["event_count"] == 1
        assert approval_audit["events"][0]["decision"] == "approved"

        exit_code = main(
            [
                "verify-outcome",
                session_id,
                *_command_roots(tmp_path),
                "--json",
            ]
        )
        assert exit_code == 0
        verify_payload = json.loads(capsys.readouterr().out)
        assert verify_payload["current_phase"] == "outcome_verification_succeeded"
        assert verify_payload["verification_rerun"] is True

        exit_code = main(
            [
                "show-audit",
                session_id,
                *_command_roots(tmp_path),
                "--event-type",
                "permission_decision",
                "--json",
            ]
        )
        assert exit_code == 0
        permission_audit = json.loads(capsys.readouterr().out)
        rollback_permission_event = next(
            event
            for event in permission_audit["events"]
            if event["decision"]["tool_name"] == "deployment_rollback_executor"
        )
        assert rollback_permission_event["decision"]["action"] == "ask"
        assert "approval was already recorded" in rollback_permission_event["decision"][
            "reason"
        ]
        assert "reviewed rollback scope" in rollback_permission_event["decision"][
            "reason"
        ]
        assert "approval was already recorded" in rollback_permission_event["summary"]
        assert (
            "not a fresh request for approval"
            in " ".join(rollback_permission_event["decision"]["provenance"]["notes"])
        )


@pytest.mark.asyncio
async def test_live_deployment_regression_cli_stops_when_service_is_already_healthy(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with DemoDeploymentTargetServer(port=0) as server:
        async with httpx.AsyncClient(timeout=5.0) as client:
            rollback_response = await client.post(f"{server.base_url}/rollback")
            rollback_response.raise_for_status()

        payload_path = _write_live_payload(
            tmp_path,
            incident_id="incident-live-already-healthy",
            session_id="session-live-already-healthy",
            base_url=server.base_url,
            expected_bad_version=server.bad_version,
            expected_previous_version=server.previous_version,
        )

        exit_code = main(
            [
                "start-incident",
                "--family",
                "deployment-regression",
                "--payload",
                str(payload_path),
                *_command_roots(tmp_path),
                "--json",
            ]
        )
        assert exit_code == 0
        start_payload = json.loads(capsys.readouterr().out)
        assert start_payload["session_id"] == "session-live-already-healthy"
        assert start_payload["current_phase"] == "action_stub_not_actionable"
        assert start_payload["approval_state"]["status"] == "none"
        assert "already shows the service healthy" in (
            start_payload["approval_state"]["reason"] or ""
        )

        working_memory_path = tmp_path / "working_memory" / "incident-live-already-healthy.json"
        working_memory_payload = json.loads(working_memory_path.read_text(encoding="utf-8"))
        assert working_memory_payload["unresolved_gaps"] == []
        assert "already healthy on the known-good version" in working_memory_payload[
            "compact_handoff_note"
        ]


@pytest.mark.asyncio
async def test_live_deployment_regression_cli_records_denial_without_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with DemoDeploymentTargetServer(port=0) as server:
        payload_path = _write_live_payload(
            tmp_path,
            incident_id="incident-live-deployment-2",
            session_id="session-live-deployment-2",
            base_url=server.base_url,
            expected_bad_version=server.bad_version,
            expected_previous_version=server.previous_version,
        )

        exit_code = main(
            [
                "start-incident",
                "--family",
                "deployment-regression",
                "--payload",
                str(payload_path),
                *_command_roots(tmp_path),
                "--json",
            ]
        )
        assert exit_code == 0
        start_payload = json.loads(capsys.readouterr().out)
        session_id = start_payload["session_id"]

        exit_code = main(
            [
                "resolve-approval",
                session_id,
                "--decision",
                "deny",
                "--reason",
                "Rollback denied for the current review.",
                *_command_roots(tmp_path),
                "--json",
            ]
        )
        assert exit_code == 0
        deny_payload = json.loads(capsys.readouterr().out)
        assert deny_payload["approval_state"]["status"] == "denied"
        assert deny_payload["current_phase"] == "action_stub_denied"

        async with httpx.AsyncClient(timeout=5.0) as client:
            deployment = (await client.get(f"{server.base_url}/deployment")).json()
            health = (await client.get(f"{server.base_url}/health")).json()
        assert deployment["current_version"] == server.bad_version
        assert health["healthy"] is False

        exit_code = main(
            [
                "show-audit",
                session_id,
                *_command_roots(tmp_path),
                "--event-type",
                "approval_resolved",
                "--json",
            ]
        )
        assert exit_code == 0
        approval_audit = json.loads(capsys.readouterr().out)
        assert approval_audit["event_count"] == 1
        assert approval_audit["events"][0]["decision"] == "denied"
