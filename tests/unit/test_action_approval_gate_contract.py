import pytest
from pydantic import ValidationError

from tools.implementations.incident_action_stub import (
    ActionCandidateType,
    ApprovalGateOutcome,
)
from tools.implementations.incident_recommendation import RecommendationApprovalLevel


def test_approval_gate_contract_accepts_pending_approval_candidate() -> None:
    gate = ApprovalGateOutcome(
        approval_required=True,
        approval_reason="Candidate must remain blocked pending review.",
        proposed_action_type=ActionCandidateType.DEPLOYMENT_VALIDATION_CANDIDATE,
        allowed_without_approval=False,
        approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
        future_preconditions=["Human approval must be recorded before any non-read-only action."],
    )

    assert gate.approval_required is True
    assert gate.approval_level is RecommendationApprovalLevel.ONCALL_LEAD


def test_approval_gate_contract_rejects_no_actionable_stub_without_reason() -> None:
    with pytest.raises(ValidationError):
        ApprovalGateOutcome(
            approval_required=False,
            approval_reason="No candidate should be proposed yet.",
            proposed_action_type=ActionCandidateType.NO_ACTIONABLE_STUB_YET,
            allowed_without_approval=False,
            approval_level=RecommendationApprovalLevel.NONE,
            conservative_reason=None,
            future_preconditions=["Stronger evidence is required."],
        )
