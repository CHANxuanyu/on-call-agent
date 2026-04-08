import pytest
from pydantic import ValidationError

from verifiers.base import (
    VerifierDefinition,
    VerifierDiagnostic,
    VerifierEvidence,
    VerifierKind,
    VerifierResult,
    VerifierRetryHint,
    VerifierStatus,
)
from verifiers.implementations.deployment_outcome_probe import DeploymentOutcomeProbeVerifier
from verifiers.implementations.deployment_rollback_execution import (
    DeploymentRollbackExecutionVerifier,
)
from verifiers.implementations.evidence_reading import EvidenceReadOutcomeVerifier
from verifiers.implementations.follow_up_investigation import FollowUpOutcomeVerifier
from verifiers.implementations.incident_action_stub import IncidentActionStubOutcomeVerifier
from verifiers.implementations.incident_hypothesis import (
    IncidentHypothesisOutcomeVerifier,
)
from verifiers.implementations.incident_recommendation import (
    IncidentRecommendationOutcomeVerifier,
)
from verifiers.implementations.incident_triage import IncidentTriageOutputVerifier


def test_verifier_result_supports_structured_diagnostics_and_evidence() -> None:
    result = VerifierResult(
        status=VerifierStatus.UNVERIFIED,
        summary="Verification could not complete within the current environment.",
        diagnostics=[
            VerifierDiagnostic(
                code="network_unavailable",
                message="upstream endpoint not reachable",
            ),
        ],
        retry_hint=VerifierRetryHint(
            should_retry=True,
            reason="Retry after network access is restored.",
            suggested_delay_seconds=30.0,
        ),
        evidence=[
            VerifierEvidence(
                kind="log",
                reference="transcripts/session-1.jsonl#line=4",
                description="Captured verification attempt output.",
            ),
        ],
    )

    assert result.status is VerifierStatus.UNVERIFIED
    assert result.retry_hint is not None
    assert result.retry_hint.should_retry is True


def test_verifier_result_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        VerifierResult.model_validate({"status": "passed", "summary": "invalid"})


def test_verifier_definition_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        VerifierDefinition.model_validate(
            {
                "kind": "mixed",
                "name": "bad_verifier",
                "description": "invalid",
                "target_condition": "invalid",
            }
        )


@pytest.mark.parametrize(
    ("verifier",),
    [
        (IncidentTriageOutputVerifier(),),
        (FollowUpOutcomeVerifier(),),
        (EvidenceReadOutcomeVerifier(),),
        (IncidentHypothesisOutcomeVerifier(),),
        (IncidentRecommendationOutcomeVerifier(),),
        (IncidentActionStubOutcomeVerifier(),),
        (DeploymentRollbackExecutionVerifier(),),
        (DeploymentOutcomeProbeVerifier(),),
    ],
)
def test_concrete_verifiers_expose_explicit_outcome_kind(verifier: object) -> None:
    definition = verifier.definition

    assert definition.kind is VerifierKind.OUTCOME
