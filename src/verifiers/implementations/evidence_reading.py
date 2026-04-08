"""Verifier for the resumable evidence-reading slice."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator

from runtime.models import SyntheticFailure
from runtime.phases import (
    EVIDENCE_VERIFIER_PHASES,
    IncidentPhase,
    require_phase_membership,
)
from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.follow_up_investigation import InvestigationTarget
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


class EvidenceReadBranch(StrEnum):
    """Branches available to the evidence-reading step."""

    READ_EVIDENCE = "read_evidence"
    INSUFFICIENT_STATE = "insufficient_state"


class EvidenceReadVerificationInput(BaseModel):
    """Structured payload verified for the evidence-reading step."""

    model_config = ConfigDict(extra="forbid")

    branch: EvidenceReadBranch
    follow_up_phase: IncidentPhase
    follow_up_verifier_passed: bool
    selected_target: InvestigationTarget | None = None
    insufficiency_reason: str | None = None
    prior_artifact_failure: SyntheticFailure | None = None
    evidence_output: EvidenceReadOutput | None = None

    @field_validator("follow_up_phase")
    @classmethod
    def _validate_follow_up_phase(cls, value: IncidentPhase) -> IncidentPhase:
        return require_phase_membership(
            phase=value,
            allowed_phases=EVIDENCE_VERIFIER_PHASES,
            boundary_name="incident_evidence_read_outcome verifier",
            phase_label="follow_up_phase",
        )


class EvidenceReadOutcomeVerifier:
    """Verifies either a justified defer/not-applicable branch or a valid evidence read."""

    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            kind=VerifierKind.OUTCOME,
            name="incident_evidence_read_outcome",
            description=(
                "Validate that the evidence-reading step either correctly defers due to missing "
                "durable target state or returns a structured evidence record."
            ),
            target_condition=(
                "The evidence-reading branch is justified by follow-up artifacts and any "
                "evidence output is structurally sufficient."
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
    ) -> EvidenceReadVerificationInput | VerifierResult:
        name_mismatch = verify_request_name(
            request=request,
            definition=self.definition,
            summary="Verifier request name does not match the evidence-reading verifier.",
        )
        if name_mismatch is not None:
            return name_mismatch

        return validate_inputs_model(
            request=request,
            model=EvidenceReadVerificationInput,
            summary="Evidence-reading verification inputs do not match the expected schema.",
            diagnostic_code="invalid_evidence_read_inputs",
            retry_reason="Repair the evidence-reading verification payload before retrying.",
        )

    def _verify_outcome(self, payload: EvidenceReadVerificationInput) -> VerifierResult:
        if payload.branch is EvidenceReadBranch.INSUFFICIENT_STATE:
            return self._verify_insufficient_state(payload)
        return self._verify_evidence_output(payload)

    def _verify_insufficient_state(
        self,
        payload: EvidenceReadVerificationInput,
    ) -> VerifierResult:
        diagnostics: list[VerifierDiagnostic] = []
        if payload.selected_target is not None:
            diagnostics.append(
                VerifierDiagnostic(
                    code="target_present_for_insufficient_state",
                    message="insufficient-state branch cannot include a selected target",
                )
            )
        if (
            payload.follow_up_phase is IncidentPhase.FOLLOW_UP_INVESTIGATION_SELECTED
            and payload.follow_up_verifier_passed
            and payload.prior_artifact_failure is None
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_selected_target",
                    message=(
                        "follow-up artifacts indicate a selected investigation target should exist"
                    ),
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary=(
                    "The insufficient-state branch is not justified by the "
                    "follow-up artifacts."
                ),
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="phase",
                        reference="follow_up_phase",
                        description=payload.follow_up_phase,
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary=(
                "The evidence-reading step correctly deferred because no "
                "durable target is available."
            ),
            evidence=[
                VerifierEvidence(
                    kind="phase",
                    reference="follow_up_phase",
                    description=payload.follow_up_phase,
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

    def _verify_evidence_output(
        self,
        payload: EvidenceReadVerificationInput,
    ) -> VerifierResult:
        if payload.selected_target is None or payload.evidence_output is None:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary=(
                    "Evidence-reading branch requires both a target and "
                    "structured evidence output."
                ),
                diagnostics=[
                    VerifierDiagnostic(
                        code="missing_evidence_output",
                        message="selected_target and evidence_output are required",
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Provide a durable target and evidence output before retrying.",
                ),
            )

        diagnostics: list[VerifierDiagnostic] = []
        if payload.evidence_output.investigation_target is not payload.selected_target:
            diagnostics.append(
                VerifierDiagnostic(
                    code="target_mismatch",
                    message="evidence output target does not match the durable selected target",
                )
            )
        if not payload.evidence_output.observations:
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_observations",
                    message="evidence output must contain at least one observation",
                )
            )
        if not payload.evidence_output.recommended_next_read_only_action.startswith(
            ("Inspect", "Review")
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="non_actionable_evidence_step",
                    message="recommended_next_read_only_action must start with Inspect or Review",
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary="The evidence-reading output is not valid for this narrow slice.",
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
            summary="The evidence-reading step produced a valid structured evidence record.",
            evidence=[
                VerifierEvidence(
                    kind="evidence_field",
                    reference="snapshot_id",
                    description=payload.evidence_output.snapshot_id,
                ),
                VerifierEvidence(
                    kind="evidence_field",
                    reference="investigation_target",
                    description=payload.evidence_output.investigation_target,
                ),
            ],
        )
