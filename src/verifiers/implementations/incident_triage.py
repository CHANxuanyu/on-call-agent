"""Verifier for the deterministic incident-triage slice."""

from __future__ import annotations

from pydantic import ValidationError

from tools.implementations.incident_triage import IncidentTriageOutput
from verifiers.base import (
    VerifierDefinition,
    VerifierDiagnostic,
    VerifierEvidence,
    VerifierRequest,
    VerifierResult,
    VerifierRetryHint,
    VerifierStatus,
)


class IncidentTriageOutputVerifier:
    """Checks that a triage result is actionable enough to count as complete."""

    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            name="incident_triage_output",
            description=(
                "Validate that triage output includes severity, blast radius, and a next action."
            ),
            target_condition=(
                "A triage result is structured and recommends a concrete read-only next step."
            ),
        )

    async def verify(self, request: VerifierRequest) -> VerifierResult:
        if request.name != self.definition.name:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="Verifier request name does not match the incident triage verifier.",
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

        raw_output = request.inputs.get("triage_output")
        if raw_output is None:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="No triage output was provided for verification.",
                diagnostics=[
                    VerifierDiagnostic(
                        code="missing_triage_output",
                        message="request.inputs.triage_output is required",
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Provide triage output before rerunning verification.",
                ),
            )

        try:
            triage_output = IncidentTriageOutput.model_validate(raw_output)
        except ValidationError as exc:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="Triage output could not be validated against the expected schema.",
                diagnostics=[
                    VerifierDiagnostic(
                        code="invalid_triage_output",
                        message=str(exc),
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Repair the triage output shape before rerunning verification.",
                ),
            )

        diagnostics: list[VerifierDiagnostic] = []
        if not triage_output.recommended_next_action.startswith(("Inspect", "Review")):
            diagnostics.append(
                VerifierDiagnostic(
                    code="non_actionable_next_step",
                    message="recommended_next_action must start with Inspect or Review",
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary=(
                    "Triage output is present but not actionable enough to mark triage complete."
                ),
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="triage_field",
                        reference="recommended_next_action",
                        description=triage_output.recommended_next_action,
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary="Triage output includes severity, blast radius, and a concrete next action.",
            evidence=[
                VerifierEvidence(
                    kind="triage_field",
                    reference="suspected_severity",
                    description=triage_output.suspected_severity,
                ),
                VerifierEvidence(
                    kind="triage_field",
                    reference="recommended_next_action",
                    description=triage_output.recommended_next_action,
                ),
            ],
        )
