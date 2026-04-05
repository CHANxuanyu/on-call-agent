import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from context.handoff_regeneration import (
    HandoffArtifactRegenerationResult,
    HandoffArtifactRegenerationStatus,
)
from memory.checkpoints import (
    ApprovalState,
    ApprovalStatus,
    OperatorAutonomyMode,
    PendingVerifier,
    SessionCheckpoint,
)
from runtime.cli import main
from tools.models import ToolCall, ToolResult, ToolResultStatus
from transcripts.models import ModelStepEvent, ToolRequestEvent, ToolResultEvent
from verifiers.base import VerifierRequest


def _fake_artifact_context() -> SimpleNamespace:
    checkpoint = SessionCheckpoint(
        checkpoint_id="session-1-checkpoint",
        session_id="session-1",
        incident_id="incident-1",
        current_phase="recommendation_supported",
        current_step=5,
        selected_skills=["incident-triage"],
        pending_verifier=PendingVerifier(
            verifier_name="incident_recommendation_outcome",
            request=VerifierRequest(
                name="incident_recommendation_outcome",
                target="incident-1",
                inputs={"recommendation": "validate_recent_deployment"},
            ),
        ),
        approval_state=ApprovalState(status=ApprovalStatus.NONE),
        summary_of_progress="Recommendation step completed successfully.",
    )
    transcript_events = (
        ModelStepEvent(
            session_id="session-1",
            step_index=1,
            summary="Prepared the triage step.",
            selected_skills=["incident-triage"],
            planned_verifiers=["incident_triage_output"],
        ),
        ToolRequestEvent(
            session_id="session-1",
            step_index=1,
            call_id="call-1",
            tool_call=ToolCall(name="incident_payload_summary", arguments={}),
        ),
        ToolResultEvent(
            session_id="session-1",
            step_index=1,
            call_id="call-1",
            tool_name="incident_payload_summary",
            result=ToolResult(status=ToolResultStatus.SUCCEEDED, output={}),
        ),
    )
    return SimpleNamespace(
        session_id="session-1",
        checkpoint_path=Path("sessions/checkpoints/session-1.json"),
        transcript_path=Path("sessions/transcripts/session-1.jsonl"),
        working_memory_path=Path("sessions/working_memory/incident-1.json"),
        checkpoint=checkpoint,
        transcript_events=transcript_events,
        latest_incident_working_memory=lambda: None,
        latest_triage_output=lambda: SimpleNamespace(
            tool_name="incident_payload_summary",
            verifier_name="incident_triage_output",
            has_output=False,
            is_verified=False,
            verifier_status=None,
            invalid_output_detail=None,
            synthetic_failure=None,
            output=None,
        ),
        latest_verified_triage_output=lambda: SimpleNamespace(
            is_available=False,
            is_success=False,
            is_insufficient=True,
            is_failure=False,
            reason="Prior artifacts do not yet contain a verifier-passed triage record.",
            artifact=None,
            insufficiency=SimpleNamespace(
                model_dump=lambda mode="json": {
                    "message": (
                        "Prior artifacts do not yet contain a verifier-passed triage record."
                    )
                }
            ),
            failure=None,
        ),
        latest_follow_up_output=lambda: SimpleNamespace(
            tool_name="investigation_focus_selector",
            verifier_name="incident_follow_up_outcome",
            has_output=False,
            is_verified=False,
            verifier_status=None,
            invalid_output_detail=None,
            synthetic_failure=None,
            output=None,
        ),
        latest_verified_follow_up_output=lambda: SimpleNamespace(
            is_available=False,
            is_success=False,
            is_insufficient=True,
            is_failure=False,
            reason=(
                "Prior artifacts do not yet contain a verifier-passed follow-up "
                "investigation target."
            ),
            artifact=None,
            insufficiency=SimpleNamespace(
                model_dump=lambda mode="json": {
                    "message": (
                        "Prior artifacts do not yet contain a verifier-passed follow-up "
                        "investigation target."
                    )
                }
            ),
            failure=None,
        ),
        latest_evidence_output=lambda: SimpleNamespace(
            tool_name="evidence_bundle_reader",
            verifier_name="incident_evidence_read_outcome",
            has_output=False,
            is_verified=False,
            verifier_status=None,
            invalid_output_detail=None,
            synthetic_failure=None,
            output=None,
        ),
        latest_verified_evidence_output=lambda: SimpleNamespace(
            is_available=False,
            is_success=False,
            is_insufficient=True,
            is_failure=False,
            reason="Prior artifacts do not yet contain a verifier-passed evidence record.",
            artifact=None,
            insufficiency=SimpleNamespace(
                model_dump=lambda mode="json": {
                    "message": (
                        "Prior artifacts do not yet contain a verifier-passed evidence "
                        "record."
                    )
                }
            ),
            failure=None,
        ),
        latest_hypothesis_output=lambda: SimpleNamespace(
            tool_name="incident_hypothesis_builder",
            verifier_name="incident_hypothesis_outcome",
            has_output=False,
            is_verified=False,
            verifier_status=None,
            invalid_output_detail=None,
            synthetic_failure=None,
            output=None,
        ),
        latest_verified_hypothesis_output=lambda: SimpleNamespace(
            is_available=False,
            is_success=False,
            is_insufficient=True,
            is_failure=False,
            reason=(
                "Prior artifacts do not yet contain a verifier-passed incident hypothesis."
            ),
            artifact=None,
            insufficiency=SimpleNamespace(
                model_dump=lambda mode="json": {
                    "message": (
                        "Prior artifacts do not yet contain a verifier-passed incident "
                        "hypothesis."
                    )
                }
            ),
            failure=None,
        ),
        latest_recommendation_output=lambda: SimpleNamespace(
            tool_name="incident_recommendation_builder",
            verifier_name="incident_recommendation_outcome",
            has_output=False,
            is_verified=False,
            verifier_status=None,
            invalid_output_detail=None,
            synthetic_failure=None,
            output=None,
        ),
        latest_verified_recommendation_output=lambda: SimpleNamespace(
            is_available=False,
            is_success=False,
            is_insufficient=True,
            is_failure=False,
            reason=(
                "Prior artifacts do not yet contain a verifier-passed recommendation record."
            ),
            artifact=None,
            insufficiency=SimpleNamespace(
                model_dump=lambda mode="json": {
                    "message": (
                        "Prior artifacts do not yet contain a verifier-passed "
                        "recommendation record."
                    )
                }
            ),
            failure=None,
        ),
        latest_action_stub_output=lambda: SimpleNamespace(
            tool_name="incident_action_stub_builder",
            verifier_name="incident_action_stub_outcome",
            has_output=False,
            is_verified=False,
            verifier_status=None,
            invalid_output_detail=None,
            synthetic_failure=None,
            output=None,
        ),
        latest_verified_action_stub_output=lambda: SimpleNamespace(
            is_available=False,
            is_success=False,
            is_insufficient=True,
            is_failure=False,
            reason=(
                "Prior artifacts do not yet contain a verifier-passed action stub record."
            ),
            artifact=None,
            insufficiency=SimpleNamespace(
                model_dump=lambda mode="json": {
                    "message": (
                        "Prior artifacts do not yet contain a verifier-passed action stub "
                        "record."
                    )
                }
            ),
            failure=None,
        ),
    )


def test_inspect_session_json_outputs_checkpoint_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "runtime.inspect.SessionArtifactContext.load",
        lambda *args, **kwargs: _fake_artifact_context(),
    )

    exit_code = main(["inspect-session", "session-1", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["session_id"] == "session-1"
    assert payload["incident_id"] == "incident-1"
    assert payload["current_phase"] == "recommendation_supported"
    assert payload["transcript_event_count"] == 3
    assert payload["working_memory_present"] is False


def test_show_audit_json_filters_event_type_and_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "runtime.inspect.SessionArtifactContext.load",
        lambda *args, **kwargs: _fake_artifact_context(),
    )

    exit_code = main(
        [
            "show-audit",
            "session-1",
            "--event-type",
            "tool_request",
            "--limit",
            "1",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["event_count"] == 1
    assert payload["events"][0]["event_type"] == "tool_request"


def test_inspect_returns_one_on_load_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("missing session")

    monkeypatch.setattr("runtime.inspect.SessionArtifactContext.load", _raise)

    exit_code = main(["inspect-session", "missing-session"])

    assert exit_code == 1
    assert "missing session" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        (HandoffArtifactRegenerationStatus.WRITTEN, 0),
        (HandoffArtifactRegenerationStatus.INSUFFICIENT, 2),
        (HandoffArtifactRegenerationStatus.FAILED, 1),
    ],
)
def test_export_handoff_maps_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: HandoffArtifactRegenerationStatus,
    expected_exit: int,
) -> None:
    result = HandoffArtifactRegenerationResult(
        session_id="session-1",
        incident_id="incident-1",
        status=status,
        checkpoint_path=Path("sessions/checkpoints/session-1.json"),
        transcript_path=Path("sessions/transcripts/session-1.jsonl"),
        working_memory_path=Path("sessions/working_memory/incident-1.json"),
        handoff_path=(
            Path("sessions/handoffs/incident-1.json")
            if status is HandoffArtifactRegenerationStatus.WRITTEN
            else None
        ),
        required_artifact="recommendation"
        if status is HandoffArtifactRegenerationStatus.INSUFFICIENT
        else None,
        insufficiency_reason=(
            "Recommendation verifier has not passed yet."
            if status is HandoffArtifactRegenerationStatus.INSUFFICIENT
            else None
        ),
    )

    monkeypatch.setattr(
        "runtime.cli.IncidentHandoffArtifactRegenerator.regenerate",
        lambda self, session_id: result,
    )

    exit_code = main(["export-handoff", "session-1", "--json"])

    assert exit_code == expected_exit
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == status.value


def test_shell_command_invokes_operator_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeShell:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self) -> int:
            return 17

    monkeypatch.setattr("runtime.cli.OperatorShell", _FakeShell)

    exit_code = main(["shell", "--mode", "semi-auto"])

    assert exit_code == 17
    assert captured["initial_mode"] is OperatorAutonomyMode.SEMI_AUTO
