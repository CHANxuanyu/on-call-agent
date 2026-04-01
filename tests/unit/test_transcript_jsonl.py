from pathlib import Path

from permissions.models import PermissionAction, PermissionDecision
from tools.models import ToolCall, ToolFailure, ToolResult, ToolResultStatus, ToolRiskLevel
from transcripts.models import (
    ModelStepEvent,
    PermissionDecisionEvent,
    ToolRequestEvent,
    ToolResultEvent,
    VerifierResultEvent,
    parse_event,
    serialize_event,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierDiagnostic, VerifierRequest, VerifierResult, VerifierStatus


def test_jsonl_transcript_store_round_trips_typed_events(tmp_path: Path) -> None:
    store = JsonlTranscriptStore(tmp_path / "session.jsonl")

    store.append(
        ModelStepEvent(
            session_id="session-1",
            step_index=1,
            summary="Perform first-pass triage.",
            selected_skills=["incident-triage"],
            planned_verifiers=["api-health-check"],
        )
    )
    store.append(
        ToolRequestEvent(
            session_id="session-1",
            step_index=2,
            call_id="tool-1",
            tool_call=ToolCall(name="read_logs", arguments={"service": "payments-api"}),
        )
    )
    store.append(
        ToolResultEvent(
            session_id="session-1",
            step_index=2,
            call_id="tool-1",
            tool_name="read_logs",
            result=ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(code="not_found", message="log source unavailable"),
            ),
        )
    )
    store.append(
        VerifierResultEvent(
            session_id="session-1",
            step_index=3,
            verifier_name="api-health-check",
            request=VerifierRequest(
                name="api-health-check",
                target="payments-api",
                inputs={"endpoint": "/healthz"},
            ),
            result=VerifierResult(
                status=VerifierStatus.FAIL,
                summary="Health endpoint returned an unhealthy response.",
                diagnostics=[
                    VerifierDiagnostic(code="http_503", message="health endpoint returned 503"),
                ],
            ),
        )
    )

    events = store.read_all()

    assert isinstance(events[0], ModelStepEvent)
    assert isinstance(events[1], ToolRequestEvent)
    assert isinstance(events[2], ToolResultEvent)
    assert isinstance(events[3], VerifierResultEvent)
    assert events[2].result.failure is not None
    assert events[3].result.status is VerifierStatus.FAIL


def test_permission_decision_event_round_trips_through_json() -> None:
    event = PermissionDecisionEvent(
        session_id="session-1",
        step_index=2,
        decision=PermissionDecision(
            tool_name="read_logs",
            risk_level=ToolRiskLevel.READ_ONLY,
            action=PermissionAction.ALLOW,
            reason="read-only tools are allowed by default",
        ),
    )

    parsed = parse_event(serialize_event(event))

    assert isinstance(parsed, PermissionDecisionEvent)
    assert parsed.decision.action is PermissionAction.ALLOW
