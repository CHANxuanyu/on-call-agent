import json
import socket
from pathlib import Path

import pytest

from memory.checkpoints import ApprovalStatus
from runtime.console_api import (
    ConsoleApprovalDecision,
    ConsoleTimelineKind,
    ConsoleVerificationStatus,
    OperatorConsoleAPI,
)
from runtime.demo_target import DemoDeploymentTargetServer
from runtime.live_surface import run_start_deployment_regression_incident


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


def test_console_api_runs_live_approval_verification_and_handoff(tmp_path: Path) -> None:
    with DemoDeploymentTargetServer(port=0) as server:
        payload_path = _write_live_payload(
            tmp_path,
            incident_id="incident-console-api-approve",
            session_id="session-console-api-approve",
            base_url=server.base_url,
            expected_bad_version=server.bad_version,
            expected_previous_version=server.previous_version,
        )

        start_payload = run_start_deployment_regression_incident(
            payload_path=payload_path,
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
        )
        session_id = str(start_payload["session_id"])

        api = OperatorConsoleAPI(
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
            handoff_root=tmp_path / "handoffs",
        )

        initial_detail = api.get_session_detail(session_id)
        initial_handoff = api.get_handoff_artifact(session_id)

        assert initial_detail.current_phase == "action_stub_pending_approval"
        assert initial_detail.approval.status is ApprovalStatus.PENDING
        assert initial_handoff.available is False

        approval = api.resolve_approval(
            session_id,
            decision=ConsoleApprovalDecision.APPROVE,
            reason="Approved from the console API integration test.",
        )

        assert approval.approval_decision is ConsoleApprovalDecision.APPROVE
        assert approval.session.current_phase == "outcome_verification_succeeded"
        assert approval.session.approval.status is ApprovalStatus.APPROVED
        assert approval.verification.status is ConsoleVerificationStatus.VERIFIED
        assert approval.verification.output is not None
        assert approval.verification.output.current_version == server.previous_version
        assert approval.verification.output.healthy is True

        rerun = api.rerun_verification(session_id)

        assert rerun.verification_rerun is True
        assert rerun.session.current_phase == "outcome_verification_succeeded"
        assert rerun.verification.status is ConsoleVerificationStatus.VERIFIED

        timeline = api.get_session_timeline(session_id, limit=20)
        kinds = [entry.kind for entry in timeline.entries]
        assert ConsoleTimelineKind.APPROVAL in kinds
        assert ConsoleTimelineKind.EXECUTION in kinds
        assert ConsoleTimelineKind.VERIFICATION in kinds

        exported = api.export_handoff_artifact(session_id)
        handoff = api.get_handoff_artifact(session_id)

        assert exported.result.status.value == "written"
        assert exported.artifact is not None
        assert handoff.available is True
        assert handoff.artifact is not None
        assert handoff.artifact.handoff.current_phase == "outcome_verification_succeeded"


def test_console_api_denies_without_changing_verification_state(tmp_path: Path) -> None:
    with DemoDeploymentTargetServer(port=0) as server:
        payload_path = _write_live_payload(
            tmp_path,
            incident_id="incident-console-api-deny",
            session_id="session-console-api-deny",
            base_url=server.base_url,
            expected_bad_version=server.bad_version,
            expected_previous_version=server.previous_version,
        )

        start_payload = run_start_deployment_regression_incident(
            payload_path=payload_path,
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
        )
        session_id = str(start_payload["session_id"])

        api = OperatorConsoleAPI(
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
            handoff_root=tmp_path / "handoffs",
        )

        denial = api.resolve_approval(
            session_id,
            decision=ConsoleApprovalDecision.DENY,
            reason="Denied from the console API integration test.",
        )

        assert denial.approval_decision is ConsoleApprovalDecision.DENY
        assert denial.session.current_phase == "action_stub_denied"
        assert denial.session.approval.status is ApprovalStatus.DENIED
        assert denial.verification.status is ConsoleVerificationStatus.INSUFFICIENT
