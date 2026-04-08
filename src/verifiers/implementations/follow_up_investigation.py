"""Verifier for the resumable follow-up slice."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from tools.implementations.follow_up_investigation import FollowUpInvestigationOutput
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
from verifiers.contracts import validate_inputs_model, verify_request_name


class FollowUpBranch(StrEnum):
    """Supported branches of the resumable follow-up step."""

    NO_OP = "no_op"
    INVESTIGATE = "investigate"


class FollowUpVerificationInput(BaseModel):
    """Structured payload verified for the follow-up step."""

    model_config = ConfigDict(extra="forbid")

    branch: FollowUpBranch
    triage_verifier_passed: bool
    triage_output: IncidentTriageOutput
    investigation_output: FollowUpInvestigationOutput | None = None


class FollowUpOutcomeVerifier:
    """Verifies that the follow-up branch choice is justified and structured."""

    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            kind=VerifierKind.OUTCOME,
            name="incident_follow_up_outcome",
            description=(
                "Validate that the resumable follow-up step either safely no-ops or selects one "
                "structured read-only investigation target."
            ),
            target_condition=(
                "The follow-up branch is justified by prior triage evidence and any "
                "investigation output is actionable."
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
    ) -> FollowUpVerificationInput | VerifierResult:
        name_mismatch = verify_request_name(
            request=request,
            definition=self.definition,
            summary="Verifier request name does not match the follow-up verifier.",
        )
        if name_mismatch is not None:
            return name_mismatch

        return validate_inputs_model(
            request=request,
            model=FollowUpVerificationInput,
            summary="Follow-up verification inputs do not match the expected schema.",
            diagnostic_code="invalid_follow_up_inputs",
            retry_reason="Repair the follow-up verification payload before retrying.",
        )

    def _verify_outcome(self, payload: FollowUpVerificationInput) -> VerifierResult:
        if payload.branch is FollowUpBranch.NO_OP:
            return self._verify_no_op(payload)
        return self._verify_investigation(payload)

    def _verify_no_op(self, payload: FollowUpVerificationInput) -> VerifierResult:
        diagnostics: list[VerifierDiagnostic] = []
        if not payload.triage_verifier_passed:
            diagnostics.append(
                VerifierDiagnostic(
                    code="triage_not_verified_complete",
                    message="safe no-op requires prior triage verifier pass",
                )
            )
        if payload.triage_output.unknowns:
            diagnostics.append(
                VerifierDiagnostic(
                    code="follow_up_required",
                    message="safe no-op requires triage output with no unresolved unknowns",
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary="The no-op branch is not justified by the prior triage artifacts.",
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="triage_field",
                        reference="unknowns",
                        description=str(payload.triage_output.unknowns),
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary="The no-op branch is justified by verified triage output with no unknowns.",
            evidence=[
                VerifierEvidence(
                    kind="triage_field",
                    reference="unknowns",
                    description="[]",
                )
            ],
        )

    def _verify_investigation(self, payload: FollowUpVerificationInput) -> VerifierResult:
        if payload.investigation_output is None:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="Investigation branch requires structured investigation output.",
                diagnostics=[
                    VerifierDiagnostic(
                        code="missing_investigation_output",
                        message="investigation_output is required for the investigation branch",
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Provide structured investigation output before retrying.",
                ),
            )

        diagnostics: list[VerifierDiagnostic] = []
        if payload.triage_verifier_passed and not payload.triage_output.unknowns:
            diagnostics.append(
                VerifierDiagnostic(
                    code="noop_should_have_been_selected",
                    message=(
                        "investigation is unnecessary when triage already passed with no unknowns"
                    ),
                )
            )
        if not payload.investigation_output.recommended_read_only_action.startswith(
            ("Inspect", "Review")
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="non_actionable_investigation_step",
                    message="recommended_read_only_action must start with Inspect or Review",
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary="The investigation branch output is not valid for this follow-up step.",
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="follow_up_field",
                        reference="recommended_read_only_action",
                        description=payload.investigation_output.recommended_read_only_action,
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary="The investigation branch selected one structured read-only follow-up action.",
            evidence=[
                VerifierEvidence(
                    kind="follow_up_field",
                    reference="investigation_target",
                    description=payload.investigation_output.investigation_target,
                )
            ],
        )
