import pytest

from tools.implementations.incident_action_stub import (
    ActionCandidateType,
    ApprovalGateOutcome,
    IncidentActionStubOutput,
)
from tools.implementations.incident_hypothesis import (
    HypothesisType,
)
from tools.implementations.incident_recommendation import (
    IncidentRecommendationOutput,
    RecommendationApprovalLevel,
    RecommendationRiskLevel,
    RecommendationType,
)
from verifiers.base import VerifierRequest, VerifierStatus
from verifiers.implementations.incident_action_stub import (
    ActionStubBranch,
    IncidentActionStubOutcomeVerifier,
)


def _supported_recommendation() -> IncidentRecommendationOutput:
    return IncidentRecommendationOutput(
        incident_id="incident-1100",
        service="payments-api",
        consumed_hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
        recommendation_type=RecommendationType.VALIDATE_RECENT_DEPLOYMENT,
        action_summary=(
            "Validate the recent deployment path for payments-api and prepare an "
            "approval review before any non-read-only action."
        ),
        justification="Deployment evidence supports a regression hypothesis.",
        risk_level=RecommendationRiskLevel.MEDIUM,
        required_approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
        preconditions=[
            "Confirm the currently deployed version still matches the suspected bad release.",
            "Confirm the previous version is a known-good rollback target.",
            "Keep all non-read-only actions blocked until on-call lead approval is recorded.",
        ],
        supporting_artifact_refs=[
            "hypothesis:deployment_regression",
            "evidence:deployment-record-2026-04-01",
        ],
        expected_outcome="A reviewed rollback or mitigation decision for payments-api.",
        rollback_or_safety_notes="Do not execute rollback without human approval.",
        more_investigation_required=True,
    )


def _conservative_recommendation() -> IncidentRecommendationOutput:
    return IncidentRecommendationOutput(
        incident_id="incident-1101",
        service="payments-api",
        consumed_hypothesis_type=HypothesisType.INSUFFICIENT_EVIDENCE,
        recommendation_type=RecommendationType.INVESTIGATE_MORE,
        action_summary=(
            "Investigate more read-only service evidence before proposing rollback "
            "or escalation for payments-api."
        ),
        justification="Current evidence is insufficient to support deployment regression.",
        risk_level=RecommendationRiskLevel.LOW,
        required_approval_level=RecommendationApprovalLevel.NONE,
        preconditions=[
            "Keep next actions read-only until deployment-specific causal evidence exists."
        ],
        supporting_artifact_refs=[
            "hypothesis:insufficient_evidence",
            "evidence:runbook-index-2026-04-01",
        ],
        expected_outcome=(
            "Additional evidence clarifies whether deployment regression is plausible."
        ),
        rollback_or_safety_notes=(
            "Avoid proposing rollback or escalation based on the current evidence quality."
        ),
        more_investigation_required=True,
    )


@pytest.mark.asyncio
async def test_incident_action_stub_verifier_passes_approval_gated_candidate() -> None:
    verifier = IncidentActionStubOutcomeVerifier()
    recommendation_output = _supported_recommendation()
    action_stub_output = IncidentActionStubOutput(
        incident_id="incident-1100",
        service="payments-api",
        consumed_recommendation_type=RecommendationType.VALIDATE_RECENT_DEPLOYMENT,
        action_candidate_type=ActionCandidateType.DEPLOYMENT_VALIDATION_CANDIDATE,
        action_candidate_created=True,
        action_summary=(
            "Propose a rollback to the previous known-good version for payments-api "
            "pending approval."
        ),
        justification="Deployment evidence supports a regression hypothesis.",
        risk_level=RecommendationRiskLevel.MEDIUM,
        supporting_artifact_refs=[
            "hypothesis:deployment_regression",
            "evidence:deployment-record-2026-04-01",
        ],
        expected_outcome="An approval-ready rollback candidate exists for payments-api.",
        safety_notes="Do not execute non-read-only actions from this stub.",
        approval_gate=ApprovalGateOutcome(
            approval_required=True,
            approval_reason="Candidate must remain blocked pending on-call lead approval.",
            proposed_action_type=ActionCandidateType.DEPLOYMENT_VALIDATION_CANDIDATE,
            allowed_without_approval=False,
            approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
            future_preconditions=[
                "Human approval must be recorded before any non-read-only action."
            ],
        ),
        future_non_read_only_action_blocked_pending_approval=True,
        more_investigation_required=True,
    )

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-1100",
            inputs={
                "branch": ActionStubBranch.BUILD_ACTION_STUB,
                "recommendation_phase": "recommendation_supported",
                "recommendation_verifier_passed": True,
                "recommendation_output": recommendation_output.model_dump(mode="json"),
                "action_stub_output": action_stub_output.model_dump(mode="json"),
            },
        )
    )

    assert result.status is VerifierStatus.PASS


@pytest.mark.asyncio
async def test_incident_action_stub_verifier_passes_no_actionable_outcome() -> None:
    verifier = IncidentActionStubOutcomeVerifier()
    recommendation_output = _conservative_recommendation()
    action_stub_output = IncidentActionStubOutput(
        incident_id="incident-1101",
        service="payments-api",
        consumed_recommendation_type=RecommendationType.INVESTIGATE_MORE,
        action_candidate_type=ActionCandidateType.NO_ACTIONABLE_STUB_YET,
        action_candidate_created=False,
        action_summary=(
            "Continue conservative investigation for payments-api; no actionable stub "
            "should proceed yet."
        ),
        justification="Current evidence is insufficient to support deployment regression.",
        risk_level=RecommendationRiskLevel.LOW,
        supporting_artifact_refs=[
            "hypothesis:insufficient_evidence",
            "evidence:runbook-index-2026-04-01",
        ],
        expected_outcome="Further read-only evidence is gathered before any candidate is proposed.",
        safety_notes="No non-read-only action candidate should be proposed yet.",
        approval_gate=ApprovalGateOutcome(
            approval_required=False,
            approval_reason="The current recommendation remains conservative.",
            proposed_action_type=ActionCandidateType.NO_ACTIONABLE_STUB_YET,
            allowed_without_approval=False,
            approval_level=RecommendationApprovalLevel.NONE,
            conservative_reason="Evidence remains insufficient for a non-read-only candidate.",
            future_preconditions=["Stronger causal evidence is required."],
        ),
        future_non_read_only_action_blocked_pending_approval=False,
        more_investigation_required=True,
    )

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-1101",
            inputs={
                "branch": ActionStubBranch.BUILD_ACTION_STUB,
                "recommendation_phase": "recommendation_conservative",
                "recommendation_verifier_passed": True,
                "recommendation_output": recommendation_output.model_dump(mode="json"),
                "action_stub_output": action_stub_output.model_dump(mode="json"),
            },
        )
    )

    assert result.status is VerifierStatus.PASS


@pytest.mark.asyncio
async def test_action_stub_verifier_rejects_insufficient_state_with_verified_recommendation(
) -> None:
    verifier = IncidentActionStubOutcomeVerifier()

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-1102",
            inputs={
                "branch": ActionStubBranch.INSUFFICIENT_STATE,
                "recommendation_phase": "recommendation_supported",
                "recommendation_verifier_passed": True,
                "insufficiency_reason": "Transcript is missing the recommendation record.",
                "recommendation_output": None,
                "action_stub_output": None,
            },
        )
    )

    assert result.status is VerifierStatus.FAIL
    assert result.diagnostics[0].code == "verified_recommendation_missing"
