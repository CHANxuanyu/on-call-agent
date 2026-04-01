import pytest

from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.implementations.incident_hypothesis import (
    HypothesisConfidence,
    HypothesisType,
    IncidentHypothesisOutput,
)
from tools.implementations.incident_recommendation import (
    IncidentRecommendationOutput,
    RecommendationApprovalLevel,
    RecommendationRiskLevel,
    RecommendationType,
)
from verifiers.base import VerifierRequest, VerifierStatus
from verifiers.implementations.incident_recommendation import (
    IncidentRecommendationOutcomeVerifier,
    RecommendationBranch,
)


def _supported_hypothesis() -> IncidentHypothesisOutput:
    return IncidentHypothesisOutput(
        incident_id="incident-900",
        service="payments-api",
        evidence_snapshot_id="deployment-record-2026-04-01",
        evidence_investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
        hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
        evidence_supported=True,
        confidence=HypothesisConfidence.MEDIUM,
        rationale_summary="Deployment evidence supports a regression hypothesis.",
        supporting_evidence_fields=["snapshot_id", "evidence_summary", "observations"],
        unresolved_gaps=["Need rollback confirmation before mitigation."],
        recommended_next_action=(
            "Review the deployment diff and validate rollback options for payments-api."
        ),
        more_investigation_required=True,
    )


def _conservative_hypothesis() -> IncidentHypothesisOutput:
    return IncidentHypothesisOutput(
        incident_id="incident-901",
        service="payments-api",
        evidence_snapshot_id="runbook-index-2026-04-01",
        evidence_investigation_target=InvestigationTarget.RUNBOOK,
        hypothesis_type=HypothesisType.INSUFFICIENT_EVIDENCE,
        evidence_supported=False,
        confidence=HypothesisConfidence.LOW,
        rationale_summary="Current evidence is insufficient to support deployment regression.",
        supporting_evidence_fields=["snapshot_id", "evidence_investigation_target"],
        unresolved_gaps=["Need deployment-specific causal evidence."],
        recommended_next_action=(
            "Inspect additional service-local evidence before asserting deployment regression."
        ),
        more_investigation_required=True,
    )


@pytest.mark.asyncio
async def test_incident_recommendation_verifier_passes_supported_recommendation() -> None:
    verifier = IncidentRecommendationOutcomeVerifier()
    hypothesis_output = _supported_hypothesis()
    recommendation_output = IncidentRecommendationOutput(
        incident_id="incident-900",
        service="payments-api",
        consumed_hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
        recommendation_type=RecommendationType.VALIDATE_RECENT_DEPLOYMENT,
        action_summary=(
            "Validate the recent deployment path for payments-api and prepare "
            "an approval review before any non-read-only action."
        ),
        justification="Deployment evidence supports a regression hypothesis.",
        risk_level=RecommendationRiskLevel.MEDIUM,
        required_approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
        preconditions=[
            "Confirm the deployment diff matches the affected request path.",
            "Keep all next actions advisory until on-call lead approval is recorded.",
        ],
        supporting_artifact_refs=[
            "hypothesis:deployment_regression",
            "evidence:deployment-record-2026-04-01",
        ],
        expected_outcome="A reviewed rollback or mitigation decision for payments-api.",
        rollback_or_safety_notes=(
            "Do not execute rollback or any write action without human approval."
        ),
        more_investigation_required=True,
    )

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-900",
            inputs={
                "branch": RecommendationBranch.BUILD_RECOMMENDATION,
                "hypothesis_phase": "hypothesis_supported",
                "hypothesis_verifier_passed": True,
                "hypothesis_output": hypothesis_output.model_dump(mode="json"),
                "recommendation_output": recommendation_output.model_dump(mode="json"),
            },
        )
    )

    assert result.status is VerifierStatus.PASS


@pytest.mark.asyncio
async def test_incident_recommendation_verifier_passes_conservative_recommendation(
) -> None:
    verifier = IncidentRecommendationOutcomeVerifier()
    hypothesis_output = _conservative_hypothesis()
    recommendation_output = IncidentRecommendationOutput(
        incident_id="incident-901",
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

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-901",
            inputs={
                "branch": RecommendationBranch.BUILD_RECOMMENDATION,
                "hypothesis_phase": "hypothesis_insufficient_evidence",
                "hypothesis_verifier_passed": True,
                "hypothesis_output": hypothesis_output.model_dump(mode="json"),
                "recommendation_output": recommendation_output.model_dump(mode="json"),
            },
        )
    )

    assert result.status is VerifierStatus.PASS


@pytest.mark.asyncio
async def test_recommendation_verifier_rejects_insufficient_state_with_verified_hypothesis(
) -> None:
    verifier = IncidentRecommendationOutcomeVerifier()

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-902",
            inputs={
                "branch": RecommendationBranch.INSUFFICIENT_STATE,
                "hypothesis_phase": "hypothesis_supported",
                "hypothesis_verifier_passed": True,
                "insufficiency_reason": "Transcript is missing the hypothesis record.",
                "hypothesis_output": None,
                "recommendation_output": None,
            },
        )
    )

    assert result.status is VerifierStatus.FAIL
    assert result.diagnostics[0].code == "verified_hypothesis_missing"
