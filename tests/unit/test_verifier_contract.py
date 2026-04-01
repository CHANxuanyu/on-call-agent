import pytest
from pydantic import ValidationError

from verifiers.base import (
    VerifierDiagnostic,
    VerifierEvidence,
    VerifierResult,
    VerifierRetryHint,
    VerifierStatus,
)


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
