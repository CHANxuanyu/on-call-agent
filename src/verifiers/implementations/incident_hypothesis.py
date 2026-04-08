"""Verifier for the resumable incident-hypothesis slice."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from runtime.models import SyntheticFailure
from runtime.phases import (
    HYPOTHESIS_VERIFIER_PHASES,
    IncidentPhase,
    require_phase_membership,
)
from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.incident_hypothesis import (
    HypothesisConfidence,
    HypothesisType,
    IncidentHypothesisOutput,
    evidence_shows_known_good_recovery,
    evidence_supports_deployment_regression,
)
from verifiers.base import (
    VerifierDefinition,
    VerifierDiagnostic,
    VerifierEvidence,
    VerifierKind,
    VerifierRequest,
    VerifierResult,
    VerifierRetryHint,
    VerifierStatus,
)
from verifiers.contracts import validate_inputs_model, verify_request_name


class HypothesisBranch(StrEnum):
    """Branches available to the incident-hypothesis step."""

    BUILD_HYPOTHESIS = "build_hypothesis"
    INSUFFICIENT_STATE = "insufficient_state"


class IncidentHypothesisVerificationInput(BaseModel):
    """Structured payload verified for the hypothesis step."""

    model_config = ConfigDict(extra="forbid")

    branch: HypothesisBranch
    evidence_phase: IncidentPhase
    evidence_verifier_passed: bool
    insufficiency_reason: str | None = None
    prior_artifact_failure: SyntheticFailure | None = None
    evidence_output: EvidenceReadOutput | None = None
    hypothesis_output: IncidentHypothesisOutput | None = None

    @field_validator("evidence_phase")
    @classmethod
    def _validate_evidence_phase(cls, value: IncidentPhase) -> IncidentPhase:
        return require_phase_membership(
            phase=value,
            allowed_phases=HYPOTHESIS_VERIFIER_PHASES,
            boundary_name="incident_hypothesis_outcome verifier",
            phase_label="evidence_phase",
        )


class IncidentHypothesisOutcomeVerifier:
    """Verifies that the hypothesis branch and output are justified by evidence."""

    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            kind=VerifierKind.OUTCOME,
            name="incident_hypothesis_outcome",
            description=(
                "Validate that the hypothesis step either correctly defers due to missing "
                "evidence artifacts or returns one justified structured hypothesis."
            ),
            target_condition=(
                "The hypothesis branch is justified by evidence artifacts and any "
                "hypothesis output matches the deterministic evidence rule."
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
    ) -> IncidentHypothesisVerificationInput | VerifierResult:
        name_mismatch = verify_request_name(
            request=request,
            definition=self.definition,
            summary="Verifier request name does not match the incident-hypothesis verifier.",
        )
        if name_mismatch is not None:
            return name_mismatch

        return validate_inputs_model(
            request=request,
            model=IncidentHypothesisVerificationInput,
            summary="Incident-hypothesis verification inputs do not match the expected schema.",
            diagnostic_code="invalid_incident_hypothesis_inputs",
            retry_reason="Repair the incident-hypothesis verification payload before retrying.",
        )

    def _verify_outcome(self, payload: IncidentHypothesisVerificationInput) -> VerifierResult:
        if payload.branch is HypothesisBranch.INSUFFICIENT_STATE:
            return self._verify_insufficient_state(payload)
        return self._verify_hypothesis(payload)

    def _verify_insufficient_state(
        self,
        payload: IncidentHypothesisVerificationInput,
    ) -> VerifierResult:
        diagnostics: list[VerifierDiagnostic] = []
        if payload.evidence_output is not None:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_evidence_output",
                    message="insufficient-state branch cannot include a consumed evidence record",
                )
            )
        if payload.hypothesis_output is not None:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_hypothesis_output",
                    message="insufficient-state branch cannot include a hypothesis output",
                )
            )
        if (
            payload.evidence_phase is IncidentPhase.EVIDENCE_READING_COMPLETED
            and payload.evidence_verifier_passed
            and payload.prior_artifact_failure is None
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="verified_evidence_missing",
                    message=(
                        "evidence artifacts indicate a verified evidence record should be "
                        "available for hypothesis building"
                    ),
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary=(
                    "The insufficient-state branch is not justified by the "
                    "prior evidence artifacts."
                ),
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="phase",
                        reference="evidence_phase",
                        description=payload.evidence_phase,
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary=(
                "The hypothesis step correctly deferred because no verified "
                "evidence record is available."
            ),
            evidence=[
                VerifierEvidence(
                    kind="phase",
                    reference="evidence_phase",
                    description=payload.evidence_phase,
                ),
                VerifierEvidence(
                    kind="reason",
                    reference="insufficiency_reason",
                    description=payload.insufficiency_reason,
                ),
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

    def _verify_hypothesis(
        self,
        payload: IncidentHypothesisVerificationInput,
    ) -> VerifierResult:
        if payload.evidence_output is None or payload.hypothesis_output is None:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary=(
                    "Hypothesis branch requires both a structured evidence record and "
                    "a structured hypothesis output."
                ),
                diagnostics=[
                    VerifierDiagnostic(
                        code="missing_hypothesis_inputs",
                        message="evidence_output and hypothesis_output are required",
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Provide evidence and hypothesis outputs before retrying.",
                ),
            )

        expected_supported = evidence_supports_deployment_regression(payload.evidence_output)
        expected_type = (
            HypothesisType.DEPLOYMENT_REGRESSION
            if expected_supported
            else HypothesisType.INSUFFICIENT_EVIDENCE
        )
        expected_confidence = (
            HypothesisConfidence.MEDIUM
            if expected_supported
            else HypothesisConfidence.LOW
        )

        diagnostics: list[VerifierDiagnostic] = []
        if payload.hypothesis_output.incident_id != payload.evidence_output.incident_id:
            diagnostics.append(
                VerifierDiagnostic(
                    code="incident_id_mismatch",
                    message="hypothesis incident_id must match the consumed evidence record",
                )
            )
        if payload.hypothesis_output.service != payload.evidence_output.service:
            diagnostics.append(
                VerifierDiagnostic(
                    code="service_mismatch",
                    message="hypothesis service must match the consumed evidence record",
                )
            )
        if payload.hypothesis_output.evidence_snapshot_id != payload.evidence_output.snapshot_id:
            diagnostics.append(
                VerifierDiagnostic(
                    code="snapshot_mismatch",
                    message="hypothesis must reference the consumed evidence snapshot",
                )
            )
        if (
            payload.hypothesis_output.evidence_investigation_target
            is not payload.evidence_output.investigation_target
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="target_mismatch",
                    message="hypothesis target must match the consumed evidence record",
                )
            )
        if payload.hypothesis_output.hypothesis_type is not expected_type:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_hypothesis_type",
                    message=(
                        f"expected hypothesis_type '{expected_type}' for the consumed evidence"
                    ),
                )
            )
        if payload.hypothesis_output.evidence_supported is not expected_supported:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unsupported_support_flag",
                    message="evidence_supported does not match the deterministic evidence rule",
                )
            )
        if payload.hypothesis_output.confidence is not expected_confidence:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_confidence",
                    message=(
                        f"expected confidence '{expected_confidence}' for this evidence branch"
                    ),
                )
            )
        if not payload.hypothesis_output.supporting_evidence_fields:
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_supporting_fields",
                    message="hypothesis must include supporting_evidence_fields",
                )
            )
        if not payload.hypothesis_output.recommended_next_action.startswith(
            ("Inspect", "Review")
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="non_actionable_next_action",
                    message="recommended_next_action must start with Inspect or Review",
                )
            )
        if not payload.hypothesis_output.more_investigation_required:
            diagnostics.append(
                VerifierDiagnostic(
                    code="investigation_flag_incorrect",
                    message="this narrow slice must leave more_investigation_required as true",
                )
            )
        if (
            not expected_supported
            and not evidence_shows_known_good_recovery(payload.evidence_output)
            and not payload.hypothesis_output.unresolved_gaps
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_unresolved_gaps",
                    message="insufficient-evidence hypothesis must retain unresolved gaps",
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary="The incident hypothesis is not justified by the consumed evidence record.",
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="evidence_field",
                        reference="snapshot_id",
                        description=payload.evidence_output.snapshot_id,
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary=(
                "The incident hypothesis is structurally valid and justified "
                "by the evidence record."
            ),
            evidence=[
                VerifierEvidence(
                    kind="evidence_field",
                    reference="snapshot_id",
                    description=payload.evidence_output.snapshot_id,
                ),
                VerifierEvidence(
                    kind="hypothesis_field",
                    reference="hypothesis_type",
                    description=payload.hypothesis_output.hypothesis_type,
                ),
            ],
        )
