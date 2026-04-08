"""Verifier for the deterministic incident-triage slice."""

from __future__ import annotations

from tools.implementations.incident_triage import IncidentTriageOutput
from verifiers.base import (
    VerifierDefinition,
    VerifierDiagnostic,
    VerifierEvidence,
    VerifierKind,
    VerifierRequest,
    VerifierResult,
    VerifierStatus,
)
from verifiers.contracts import validate_required_input_model, verify_request_name


class IncidentTriageOutputVerifier:
    """Checks that a triage result is actionable enough to count as complete."""

    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            kind=VerifierKind.OUTCOME,
            name="incident_triage_output",
            description=(
                "Validate that triage output includes severity, blast radius, and a next action."
            ),
            target_condition=(
                "A triage result is structured and recommends a concrete read-only next step."
            ),
        )

    async def verify(self, request: VerifierRequest) -> VerifierResult:
        contract = self._verify_contract(request)
        if isinstance(contract, VerifierResult):
            return contract
        return self._verify_outcome(contract)

    def _verify_contract(
        self,
        request: VerifierRequest,
    ) -> IncidentTriageOutput | VerifierResult:
        name_mismatch = verify_request_name(
            request=request,
            definition=self.definition,
            summary="Verifier request name does not match the incident triage verifier.",
        )
        if name_mismatch is not None:
            return name_mismatch

        return validate_required_input_model(
            request=request,
            input_name="triage_output",
            model=IncidentTriageOutput,
            missing_summary="No triage output was provided for verification.",
            missing_diagnostic_code="missing_triage_output",
            missing_diagnostic_message="request.inputs.triage_output is required",
            missing_retry_reason="Provide triage output before rerunning verification.",
            invalid_summary="Triage output could not be validated against the expected schema.",
            invalid_diagnostic_code="invalid_triage_output",
            invalid_retry_reason="Repair the triage output shape before rerunning verification.",
        )

    def _verify_outcome(self, triage_output: IncidentTriageOutput) -> VerifierResult:
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
