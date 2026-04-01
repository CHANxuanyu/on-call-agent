import pytest

from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.implementations.incident_hypothesis import (
    HypothesisConfidence,
    HypothesisType,
    IncidentHypothesisOutput,
)
from verifiers.base import VerifierRequest, VerifierStatus
from verifiers.implementations.incident_hypothesis import (
    HypothesisBranch,
    IncidentHypothesisOutcomeVerifier,
)


def _deployment_evidence() -> EvidenceReadOutput:
    return EvidenceReadOutput(
        incident_id="incident-700",
        service="payments-api",
        investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
        snapshot_id="deployment-record-2026-04-01",
        evidence_source="evals/fixtures/evidence_snapshots.json::recent_deployment",
        evidence_summary=(
            "A payments-api deployment completed 12 minutes before the alert and "
            "changed request timeout handling."
        ),
        observations=[
            "payments-api deploy 2026-04-01-1 completed 12 minutes before alert fire time",
            "Deployment diff reduced the downstream request timeout threshold",
        ],
        recommended_next_read_only_action="Review the deployment diff for payments-api.",
    )


def _supported_hypothesis() -> IncidentHypothesisOutput:
    return IncidentHypothesisOutput(
        incident_id="incident-700",
        service="payments-api",
        evidence_snapshot_id="deployment-record-2026-04-01",
        evidence_investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
        hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
        evidence_supported=True,
        confidence=HypothesisConfidence.MEDIUM,
        rationale_summary="The deployment evidence supports a regression hypothesis.",
        supporting_evidence_fields=["snapshot_id", "evidence_summary", "observations"],
        unresolved_gaps=["Need rollback confirmation before mitigation."],
        recommended_next_action=(
            "Review the deployment diff and validate rollback options for payments-api."
        ),
        more_investigation_required=True,
    )


@pytest.mark.asyncio
async def test_incident_hypothesis_verifier_passes_supported_hypothesis() -> None:
    verifier = IncidentHypothesisOutcomeVerifier()
    evidence_output = _deployment_evidence()
    hypothesis_output = _supported_hypothesis()

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-700",
            inputs={
                "branch": HypothesisBranch.BUILD_HYPOTHESIS,
                "evidence_phase": "evidence_reading_completed",
                "evidence_verifier_passed": True,
                "evidence_output": evidence_output.model_dump(mode="json"),
                "hypothesis_output": hypothesis_output.model_dump(mode="json"),
            },
        )
    )

    assert result.status is VerifierStatus.PASS


@pytest.mark.asyncio
async def test_incident_hypothesis_verifier_passes_insufficient_evidence_hypothesis() -> None:
    verifier = IncidentHypothesisOutcomeVerifier()
    evidence_output = EvidenceReadOutput(
        incident_id="incident-701",
        service="payments-api",
        investigation_target=InvestigationTarget.RUNBOOK,
        snapshot_id="runbook-index-2026-04-01",
        evidence_source="evals/fixtures/evidence_snapshots.json::runbook",
        evidence_summary=(
            "The runbook index links payments-api triage to dependency timeout checks."
        ),
        observations=["Runbook section 1 recommends checking recent releases first"],
        recommended_next_read_only_action=(
            "Review the payments-api runbook section for dependency timeout checks."
        ),
    )
    hypothesis_output = IncidentHypothesisOutput(
        incident_id="incident-701",
        service="payments-api",
        evidence_snapshot_id="runbook-index-2026-04-01",
        evidence_investigation_target=InvestigationTarget.RUNBOOK,
        hypothesis_type=HypothesisType.INSUFFICIENT_EVIDENCE,
        evidence_supported=False,
        confidence=HypothesisConfidence.LOW,
        rationale_summary=(
            "The runbook evidence does not directly support a deployment regression."
        ),
        supporting_evidence_fields=["snapshot_id", "evidence_investigation_target"],
        unresolved_gaps=[
            "Need deployment-specific causal evidence before asserting deployment regression."
        ],
        recommended_next_action=(
            "Inspect additional service-local evidence before asserting deployment "
            "regression for payments-api."
        ),
        more_investigation_required=True,
    )

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-701",
            inputs={
                "branch": HypothesisBranch.BUILD_HYPOTHESIS,
                "evidence_phase": "evidence_reading_completed",
                "evidence_verifier_passed": True,
                "evidence_output": evidence_output.model_dump(mode="json"),
                "hypothesis_output": hypothesis_output.model_dump(mode="json"),
            },
        )
    )

    assert result.status is VerifierStatus.PASS


@pytest.mark.asyncio
async def test_hypothesis_verifier_rejects_insufficient_state_with_verified_evidence(
) -> None:
    verifier = IncidentHypothesisOutcomeVerifier()

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-702",
            inputs={
                "branch": HypothesisBranch.INSUFFICIENT_STATE,
                "evidence_phase": "evidence_reading_completed",
                "evidence_verifier_passed": True,
                "insufficiency_reason": "Transcript is missing the evidence record.",
                "evidence_output": None,
                "hypothesis_output": None,
            },
        )
    )

    assert result.status is VerifierStatus.FAIL
    assert result.diagnostics[0].code == "verified_evidence_missing"
