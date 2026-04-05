"""Verifier for the post-action deployment outcome probe."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError

from runtime.models import SyntheticFailure
from tools.implementations.deployment_outcome_probe import DeploymentOutcomeProbeOutput
from verifiers.base import (
    VerifierDefinition,
    VerifierDiagnostic,
    VerifierEvidence,
    VerifierRequest,
    VerifierResult,
    VerifierRetryHint,
    VerifierStatus,
)


class OutcomeProbeBranch(StrEnum):
    """Branches available to the outcome verification step."""

    PROBE_OUTCOME = "probe_outcome"
    INSUFFICIENT_STATE = "insufficient_state"


class DeploymentOutcomeVerificationInput(BaseModel):
    """Structured payload verified for the outcome verification step."""

    model_config = ConfigDict(extra="forbid")

    branch: OutcomeProbeBranch
    insufficiency_reason: str | None = None
    prior_artifact_failure: SyntheticFailure | None = None
    outcome_probe_output: DeploymentOutcomeProbeOutput | None = None


class DeploymentOutcomeProbeVerifier:
    """Verify recovery using live runtime state after a bounded rollback."""

    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            name="deployment_outcome_verification",
            description=(
                "Validate whether the live runtime state indicates successful recovery after a "
                "bounded rollback."
            ),
            target_condition=(
                "The service is healthy again, error metrics are low, and the current version "
                "matches the expected rollback target."
            ),
        )

    async def verify(self, request: VerifierRequest) -> VerifierResult:
        if request.name != self.definition.name:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="Verifier request name does not match the outcome probe verifier.",
                diagnostics=[
                    VerifierDiagnostic(
                        code="verifier_name_mismatch",
                        message=(
                            f"expected verifier '{self.definition.name}' but received "
                            f"'{request.name}'"
                        ),
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Fix the verifier selection before retrying.",
                ),
            )

        try:
            payload = DeploymentOutcomeVerificationInput.model_validate(request.inputs)
        except ValidationError as exc:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="Outcome probe verification inputs do not match the expected schema.",
                diagnostics=[
                    VerifierDiagnostic(
                        code="invalid_outcome_probe_inputs",
                        message=str(exc),
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Repair the outcome probe verification payload before retrying.",
                ),
            )

        if payload.branch is OutcomeProbeBranch.INSUFFICIENT_STATE:
            return self._verify_insufficient_state(payload)
        return self._verify_probe_output(payload)

    def _verify_insufficient_state(
        self,
        payload: DeploymentOutcomeVerificationInput,
    ) -> VerifierResult:
        return VerifierResult(
            status=VerifierStatus.PASS,
            summary=(
                "Outcome verification correctly deferred because no verified rollback execution "
                "artifact is available yet."
            ),
            evidence=[
                VerifierEvidence(
                    kind="reason",
                    reference="insufficiency_reason",
                    description=payload.insufficiency_reason,
                )
            ],
            diagnostics=(
                [
                    VerifierDiagnostic(
                        code=payload.prior_artifact_failure.code.value,
                        message=payload.prior_artifact_failure.reason,
                    )
                ]
                if payload.prior_artifact_failure is not None
                else []
            ),
        )

    def _verify_probe_output(
        self,
        payload: DeploymentOutcomeVerificationInput,
    ) -> VerifierResult:
        if payload.outcome_probe_output is None:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="Outcome verification requires a structured runtime probe output.",
                diagnostics=[
                    VerifierDiagnostic(
                        code="missing_outcome_probe_output",
                        message="outcome_probe_output is required",
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Provide the runtime probe output before retrying verification.",
                ),
            )

        output = payload.outcome_probe_output
        diagnostics: list[VerifierDiagnostic] = []
        if not output.healthy:
            diagnostics.append(
                VerifierDiagnostic(
                    code="service_still_unhealthy",
                    message="runtime probe still reports the service as unhealthy",
                )
            )
        if output.error_rate > 0.05:
            diagnostics.append(
                VerifierDiagnostic(
                    code="error_rate_too_high",
                    message=f"runtime probe error_rate {output.error_rate:.2f} exceeds 0.05",
                )
            )
        if output.timeout_rate > 0.05:
            diagnostics.append(
                VerifierDiagnostic(
                    code="timeout_rate_too_high",
                    message=(
                        f"runtime probe timeout_rate {output.timeout_rate:.2f} exceeds 0.05"
                    ),
                )
            )
        if (
            output.expected_previous_version is not None
            and output.current_version != output.expected_previous_version
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="version_not_rolled_back",
                    message=(
                        f"runtime probe version '{output.current_version}' does not match "
                        f"expected_previous_version '{output.expected_previous_version}'"
                    ),
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary=(
                    "The live runtime probe does not yet show a clean recovery after rollback."
                ),
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="runtime_field",
                        reference="summary",
                        description=output.summary,
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=True,
                    reason="Probe again if the service may still be converging after rollback.",
                    suggested_delay_seconds=5.0,
                ),
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary="The live runtime probe confirms the service recovered after rollback.",
            evidence=[
                VerifierEvidence(
                    kind="runtime_field",
                    reference="current_version",
                    description=output.current_version,
                ),
                VerifierEvidence(
                    kind="runtime_field",
                    reference="health_status",
                    description=output.health_status,
                ),
            ],
        )
