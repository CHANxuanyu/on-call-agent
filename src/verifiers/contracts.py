"""Reusable helpers for explicit verifier contract stages."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from verifiers.base import (
    VerifierDefinition,
    VerifierDiagnostic,
    VerifierRequest,
    VerifierResult,
    VerifierRetryHint,
    VerifierStatus,
)

ContractModelT = TypeVar("ContractModelT", bound=BaseModel)


def verify_request_name(
    *,
    request: VerifierRequest,
    definition: VerifierDefinition,
    summary: str,
) -> VerifierResult | None:
    """Return a typed contract failure when the selected verifier is wrong."""

    if request.name == definition.name:
        return None
    return VerifierResult(
        status=VerifierStatus.UNVERIFIED,
        summary=summary,
        diagnostics=[
            VerifierDiagnostic(
                code="verifier_name_mismatch",
                message=(
                    f"expected verifier '{definition.name}' but received "
                    f"'{request.name}'"
                ),
            )
        ],
        retry_hint=VerifierRetryHint(
            should_retry=False,
            reason="Fix the verifier selection before retrying.",
        ),
    )


def validate_inputs_model(
    *,
    request: VerifierRequest,
    model: type[ContractModelT],
    summary: str,
    diagnostic_code: str,
    retry_reason: str,
) -> ContractModelT | VerifierResult:
    """Validate the full verifier inputs payload against one contract model."""

    try:
        return model.model_validate(request.inputs)
    except ValidationError as exc:
        return VerifierResult(
            status=VerifierStatus.UNVERIFIED,
            summary=summary,
            diagnostics=[
                VerifierDiagnostic(
                    code=diagnostic_code,
                    message=str(exc),
                )
            ],
            retry_hint=VerifierRetryHint(
                should_retry=False,
                reason=retry_reason,
            ),
        )


def validate_required_input_model(
    *,
    request: VerifierRequest,
    input_name: str,
    model: type[ContractModelT],
    missing_summary: str,
    missing_diagnostic_code: str,
    missing_diagnostic_message: str,
    missing_retry_reason: str,
    invalid_summary: str,
    invalid_diagnostic_code: str,
    invalid_retry_reason: str,
) -> ContractModelT | VerifierResult:
    """Validate one required verifier input against its typed contract model."""

    raw_input = request.inputs.get(input_name)
    if raw_input is None:
        return VerifierResult(
            status=VerifierStatus.UNVERIFIED,
            summary=missing_summary,
            diagnostics=[
                VerifierDiagnostic(
                    code=missing_diagnostic_code,
                    message=missing_diagnostic_message,
                )
            ],
            retry_hint=VerifierRetryHint(
                should_retry=False,
                reason=missing_retry_reason,
            ),
        )

    try:
        return model.model_validate(raw_input)
    except ValidationError as exc:
        return VerifierResult(
            status=VerifierStatus.UNVERIFIED,
            summary=invalid_summary,
            diagnostics=[
                VerifierDiagnostic(
                    code=invalid_diagnostic_code,
                    message=str(exc),
                )
            ],
            retry_hint=VerifierRetryHint(
                should_retry=False,
                reason=invalid_retry_reason,
            ),
        )
