"""Verifier for the resumable recommendation slice."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError

from runtime.models import SyntheticFailure
from tools.implementations.incident_hypothesis import (
    HypothesisType,
    IncidentHypothesisOutput,
)
from tools.implementations.incident_recommendation import (
    IncidentRecommendationOutput,
    RecommendationApprovalLevel,
    RecommendationRiskLevel,
    RecommendationType,
)
from verifiers.base import (
    VerifierDefinition,
    VerifierDiagnostic,
    VerifierEvidence,
    VerifierRequest,
    VerifierResult,
    VerifierRetryHint,
    VerifierStatus,
)


class RecommendationBranch(StrEnum):
    """Branches available to the recommendation step."""

    BUILD_RECOMMENDATION = "build_recommendation"
    INSUFFICIENT_STATE = "insufficient_state"


class IncidentRecommendationVerificationInput(BaseModel):
    """Structured payload verified for the recommendation step."""

    model_config = ConfigDict(extra="forbid")

    branch: RecommendationBranch
    hypothesis_phase: str
    hypothesis_verifier_passed: bool
    insufficiency_reason: str | None = None
    prior_artifact_failure: SyntheticFailure | None = None
    hypothesis_output: IncidentHypothesisOutput | None = None
    recommendation_output: IncidentRecommendationOutput | None = None


class IncidentRecommendationOutcomeVerifier:
    """Verifies that a recommendation is justified and conservative when needed."""

    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            name="incident_recommendation_outcome",
            description=(
                "Validate that the recommendation step either correctly defers due to "
                "missing hypothesis artifacts or returns one justified action proposal."
            ),
            target_condition=(
                "The recommendation branch is justified by the hypothesis artifacts and "
                "does not overreach beyond the current evidence quality."
            ),
        )

    async def verify(self, request: VerifierRequest) -> VerifierResult:
        if request.name != self.definition.name:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="Verifier request name does not match the recommendation verifier.",
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
            payload = IncidentRecommendationVerificationInput.model_validate(request.inputs)
        except ValidationError as exc:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="Recommendation verification inputs do not match the expected schema.",
                diagnostics=[
                    VerifierDiagnostic(
                        code="invalid_incident_recommendation_inputs",
                        message=str(exc),
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Repair the recommendation verification payload before retrying.",
                ),
            )

        if payload.branch is RecommendationBranch.INSUFFICIENT_STATE:
            return self._verify_insufficient_state(payload)
        return self._verify_recommendation(payload)

    def _verify_insufficient_state(
        self,
        payload: IncidentRecommendationVerificationInput,
    ) -> VerifierResult:
        diagnostics: list[VerifierDiagnostic] = []
        if payload.hypothesis_output is not None:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_hypothesis_output",
                    message="insufficient-state branch cannot include a hypothesis output",
                )
            )
        if payload.recommendation_output is not None:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_recommendation_output",
                    message="insufficient-state branch cannot include a recommendation output",
                )
            )
        if (
            payload.hypothesis_phase in {"hypothesis_supported", "hypothesis_insufficient_evidence"}
            and payload.hypothesis_verifier_passed
            and payload.prior_artifact_failure is None
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="verified_hypothesis_missing",
                    message=(
                        "hypothesis artifacts indicate a verified hypothesis record should "
                        "be available for recommendation building"
                    ),
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary=(
                    "The insufficient-state branch is not justified by the prior "
                    "hypothesis artifacts."
                ),
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="phase",
                        reference="hypothesis_phase",
                        description=payload.hypothesis_phase,
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary=(
                "The recommendation step correctly deferred because no verified "
                "hypothesis record is available."
            ),
            evidence=[
                VerifierEvidence(
                    kind="phase",
                    reference="hypothesis_phase",
                    description=payload.hypothesis_phase,
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

    def _verify_recommendation(
        self,
        payload: IncidentRecommendationVerificationInput,
    ) -> VerifierResult:
        if payload.hypothesis_output is None or payload.recommendation_output is None:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary=(
                    "Recommendation branch requires both a structured hypothesis record "
                    "and a structured recommendation output."
                ),
                diagnostics=[
                    VerifierDiagnostic(
                        code="missing_recommendation_inputs",
                        message="hypothesis_output and recommendation_output are required",
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Provide hypothesis and recommendation outputs before retrying.",
                ),
            )

        if (
            payload.hypothesis_output.hypothesis_type is HypothesisType.DEPLOYMENT_REGRESSION
            and payload.hypothesis_output.evidence_supported
        ):
            expected_type = RecommendationType.VALIDATE_RECENT_DEPLOYMENT
            expected_risk = RecommendationRiskLevel.MEDIUM
            expected_approval = RecommendationApprovalLevel.ONCALL_LEAD
        else:
            expected_type = RecommendationType.INVESTIGATE_MORE
            expected_risk = RecommendationRiskLevel.LOW
            expected_approval = RecommendationApprovalLevel.NONE

        diagnostics: list[VerifierDiagnostic] = []
        if payload.recommendation_output.incident_id != payload.hypothesis_output.incident_id:
            diagnostics.append(
                VerifierDiagnostic(
                    code="incident_id_mismatch",
                    message="recommendation incident_id must match the hypothesis record",
                )
            )
        if payload.recommendation_output.service != payload.hypothesis_output.service:
            diagnostics.append(
                VerifierDiagnostic(
                    code="service_mismatch",
                    message="recommendation service must match the hypothesis record",
                )
            )
        if (
            payload.recommendation_output.consumed_hypothesis_type
            is not payload.hypothesis_output.hypothesis_type
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="hypothesis_type_mismatch",
                    message="recommendation must reference the consumed hypothesis type",
                )
            )
        if payload.recommendation_output.recommendation_type is not expected_type:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_recommendation_type",
                    message=(
                        f"expected recommendation_type '{expected_type}' for the "
                        "consumed hypothesis"
                    ),
                )
            )
        if payload.recommendation_output.risk_level is not expected_risk:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_risk_level",
                    message=f"expected risk_level '{expected_risk}' for this hypothesis",
                )
            )
        if (
            payload.recommendation_output.required_approval_level
            is not expected_approval
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_approval_level",
                    message=(
                        f"expected required_approval_level '{expected_approval}' for "
                        "this hypothesis"
                    ),
                )
            )
        if not payload.recommendation_output.preconditions:
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_preconditions",
                    message="recommendation must include at least one precondition",
                )
            )
        if not payload.recommendation_output.supporting_artifact_refs:
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_supporting_refs",
                    message="recommendation must include supporting_artifact_refs",
                )
            )
        if not payload.recommendation_output.expected_outcome:
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_expected_outcome",
                    message="recommendation must include an expected_outcome",
                )
            )
        if not payload.recommendation_output.action_summary.startswith(
            ("Validate", "Investigate", "Prepare")
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="non_actionable_summary",
                    message="action_summary must start with Validate, Investigate, or Prepare",
                )
            )
        if not payload.recommendation_output.more_investigation_required:
            diagnostics.append(
                VerifierDiagnostic(
                    code="investigation_flag_incorrect",
                    message="this narrow slice must leave more_investigation_required as true",
                )
            )
        if (
            expected_type is RecommendationType.INVESTIGATE_MORE
            and payload.recommendation_output.required_approval_level
            is not RecommendationApprovalLevel.NONE
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="conservative_recommendation_overreaches",
                    message=(
                        "conservative recommendation cannot require approval for a "
                        "future non-read-only action"
                    ),
                )
            )
        if (
            expected_type is RecommendationType.VALIDATE_RECENT_DEPLOYMENT
            and payload.recommendation_output.rollback_or_safety_notes is None
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_safety_notes",
                    message=(
                        "supported recommendation must include rollback_or_safety_notes"
                    ),
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary=(
                    "The incident recommendation is not justified by the consumed "
                    "hypothesis record."
                ),
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="hypothesis_field",
                        reference="hypothesis_type",
                        description=payload.hypothesis_output.hypothesis_type,
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary=(
                "The incident recommendation is structurally valid and justified by "
                "the hypothesis record."
            ),
            evidence=[
                VerifierEvidence(
                    kind="hypothesis_field",
                    reference="hypothesis_type",
                    description=payload.hypothesis_output.hypothesis_type,
                ),
                VerifierEvidence(
                    kind="recommendation_field",
                    reference="recommendation_type",
                    description=payload.recommendation_output.recommendation_type,
                ),
            ],
        )
