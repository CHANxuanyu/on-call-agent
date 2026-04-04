from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from memory.checkpoints import (
    ApprovalState,
    ApprovalStatus,
    PendingVerifier,
    SessionCheckpoint,
)
from tools.models import ToolCall
from verifiers.base import VerifierRequest


def test_session_checkpoint_models_resumable_state() -> None:
    checkpoint = SessionCheckpoint(
        checkpoint_id="chk-0001",
        session_id="session-1",
        incident_id="incident-42",
        current_phase="verification",
        current_step=5,
        selected_skills=["incident-triage"],
        pending_tool_call=ToolCall(name="read_logs", arguments={"service": "payments-api"}),
        pending_verifier=PendingVerifier(
            verifier_name="api-health-check",
            request=VerifierRequest(
                name="api-health-check",
                target="payments-api",
                inputs={"endpoint": "/healthz"},
            ),
        ),
        approval_state=ApprovalState(
            status=ApprovalStatus.PENDING,
            requested_action="restart_service",
            reason="Pending human approval",
            future_preconditions=[
                "Record explicit approval before any non-read-only action."
            ],
            updated_at=datetime(2026, 4, 1, tzinfo=UTC),
        ),
        summary_of_progress="Read-only evidence collected and verification queued.",
    )

    assert checkpoint.pending_tool_call is not None
    assert checkpoint.pending_verifier is not None
    assert checkpoint.approval_state.status is ApprovalStatus.PENDING
    assert checkpoint.approval_state.future_preconditions == [
        "Record explicit approval before any non-read-only action."
    ]


def test_session_checkpoint_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SessionCheckpoint.model_validate(
            {
                "checkpoint_id": "chk-0002",
                "session_id": "session-2",
                "incident_id": "incident-43",
                "current_phase": "triage",
                "current_step": 1,
                "summary_of_progress": "Started triage.",
                "unexpected_field": "nope",
            }
        )
