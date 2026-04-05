"""Verifier for the approval-gated action stub slice."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError

from runtime.models import SyntheticFailure
from tools.implementations.incident_action_stub import (
    ActionCandidateType,
    IncidentActionStubOutput,
)
from tools.implementations.incident_recommendation import (
    IncidentRecommendationOutput,
    RecommendationApprovalLevel,
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


class ActionStubBranch(StrEnum):
    """Branches available to the action-stub step."""

    BUILD_ACTION_STUB = "build_action_stub"
    INSUFFICIENT_STATE = "insufficient_state"


class IncidentActionStubVerificationInput(BaseModel):
    """Structured payload verified for the action-stub step."""

    model_config = ConfigDict(extra="forbid")

    branch: ActionStubBranch
    recommendation_phase: str
    recommendation_verifier_passed: bool
    insufficiency_reason: str | None = None
    prior_artifact_failure: SyntheticFailure | None = None
    recommendation_output: IncidentRecommendationOutput | None = None
    action_stub_output: IncidentActionStubOutput | None = None


class IncidentActionStubOutcomeVerifier:
    """Verifies that the action stub is justified and remains non-executing."""

    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            name="incident_action_stub_outcome",
            description=(
                "Validate that the action-stub step either correctly defers due to "
                "missing recommendation artifacts or returns one justified approval-aware "
                "action stub."
            ),
            target_condition=(
                "The action-stub branch is justified by the recommendation artifacts and "
                "never overreaches into unapproved execution."
            ),
        )

    async def verify(self, request: VerifierRequest) -> VerifierResult:
        if request.name != self.definition.name:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="Verifier request name does not match the action-stub verifier.",
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
            payload = IncidentActionStubVerificationInput.model_validate(request.inputs)
        except ValidationError as exc:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary="Action-stub verification inputs do not match the expected schema.",
                diagnostics=[
                    VerifierDiagnostic(
                        code="invalid_incident_action_stub_inputs",
                        message=str(exc),
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Repair the action-stub verification payload before retrying.",
                ),
            )

        if payload.branch is ActionStubBranch.INSUFFICIENT_STATE:
            return self._verify_insufficient_state(payload)
        return self._verify_action_stub(payload)

    def _verify_insufficient_state(
        self,
        payload: IncidentActionStubVerificationInput,
    ) -> VerifierResult:
        diagnostics: list[VerifierDiagnostic] = []
        if payload.recommendation_output is not None:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_recommendation_output",
                    message="insufficient-state branch cannot include a recommendation output",
                )
            )
        if payload.action_stub_output is not None:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_action_stub_output",
                    message="insufficient-state branch cannot include an action stub output",
                )
            )
        if (
            payload.recommendation_phase
            in {"recommendation_supported", "recommendation_conservative"}
            and payload.recommendation_verifier_passed
            and payload.prior_artifact_failure is None
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="verified_recommendation_missing",
                    message=(
                        "recommendation artifacts indicate a verified recommendation "
                        "record should be available for action-stub building"
                    ),
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary=(
                    "The insufficient-state branch is not justified by the prior "
                    "recommendation artifacts."
                ),
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="phase",
                        reference="recommendation_phase",
                        description=payload.recommendation_phase,
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary=(
                "The action-stub step correctly deferred because no verified "
                "recommendation record is available."
            ),
            evidence=[
                VerifierEvidence(
                    kind="phase",
                    reference="recommendation_phase",
                    description=payload.recommendation_phase,
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

    def _verify_action_stub(
        self,
        payload: IncidentActionStubVerificationInput,
    ) -> VerifierResult:
        if payload.recommendation_output is None or payload.action_stub_output is None:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary=(
                    "Action-stub branch requires both a structured recommendation "
                    "record and a structured action stub output."
                ),
                diagnostics=[
                    VerifierDiagnostic(
                        code="missing_action_stub_inputs",
                        message="recommendation_output and action_stub_output are required",
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Provide recommendation and action stub outputs before retrying.",
                ),
            )

        if (
            payload.recommendation_output.recommendation_type
            is RecommendationType.VALIDATE_RECENT_DEPLOYMENT
            and payload.recommendation_output.required_approval_level
            is not RecommendationApprovalLevel.NONE
        ):
            expected_candidate_type = (
                ActionCandidateType.ROLLBACK_RECENT_DEPLOYMENT_CANDIDATE
            )
            expected_created = True
            expected_approval_required = True
            expected_blocked_pending_approval = True
        else:
            expected_candidate_type = ActionCandidateType.NO_ACTIONABLE_STUB_YET
            expected_created = False
            expected_approval_required = False
            expected_blocked_pending_approval = False

        diagnostics: list[VerifierDiagnostic] = []
        if payload.action_stub_output.incident_id != payload.recommendation_output.incident_id:
            diagnostics.append(
                VerifierDiagnostic(
                    code="incident_id_mismatch",
                    message="action stub incident_id must match the recommendation record",
                )
            )
        if payload.action_stub_output.service != payload.recommendation_output.service:
            diagnostics.append(
                VerifierDiagnostic(
                    code="service_mismatch",
                    message="action stub service must match the recommendation record",
                )
            )
        if (
            payload.action_stub_output.consumed_recommendation_type
            is not payload.recommendation_output.recommendation_type
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="recommendation_type_mismatch",
                    message="action stub must reference the consumed recommendation type",
                )
            )
        if payload.action_stub_output.action_candidate_type is not expected_candidate_type:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_action_candidate_type",
                    message=(
                        f"expected action_candidate_type '{expected_candidate_type}' for "
                        "the consumed recommendation"
                    ),
                )
            )
        if payload.action_stub_output.action_candidate_created is not expected_created:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_action_candidate_created",
                    message="action_candidate_created does not match the recommendation branch",
                )
            )
        if (
            payload.action_stub_output.approval_gate.approval_required
            is not expected_approval_required
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_approval_requirement",
                    message="approval_required does not match the recommendation branch",
                )
            )
        if (
            payload.action_stub_output.future_non_read_only_action_blocked_pending_approval
            is not expected_blocked_pending_approval
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_pending_approval_flag",
                    message=(
                        "future_non_read_only_action_blocked_pending_approval does not "
                        "match the recommendation branch"
                    ),
                )
            )
        if payload.action_stub_output.approval_gate.allowed_without_approval:
            diagnostics.append(
                VerifierDiagnostic(
                    code="unapproved_execution_exposed",
                    message="action stub cannot allow execution without approval",
                )
            )
        if not payload.action_stub_output.supporting_artifact_refs:
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_supporting_refs",
                    message="action stub must include supporting_artifact_refs",
                )
            )
        if not payload.action_stub_output.expected_outcome:
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_expected_outcome",
                    message="action stub must include expected_outcome",
                )
            )
        if not payload.action_stub_output.safety_notes:
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_safety_notes",
                    message="action stub must include safety_notes",
                )
            )
        if not payload.action_stub_output.more_investigation_required:
            diagnostics.append(
                VerifierDiagnostic(
                    code="investigation_flag_incorrect",
                    message="this narrow slice must leave more_investigation_required as true",
                )
            )
        if not payload.action_stub_output.action_summary.startswith(("Propose", "Continue")):
            diagnostics.append(
                VerifierDiagnostic(
                    code="non_actionable_summary",
                    message="action_summary must start with Propose or Continue",
                )
            )
        if expected_created and (
            payload.action_stub_output.approval_gate.approval_level
            is RecommendationApprovalLevel.NONE
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_approval_level",
                    message="approval-gated candidate must carry a non-none approval level",
                )
            )
        if not expected_created and (
            payload.action_stub_output.approval_gate.conservative_reason is None
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="missing_conservative_reason",
                    message="no-actionable outcome must include conservative_reason",
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary=(
                    "The incident action stub is not justified by the consumed "
                    "recommendation record."
                ),
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="recommendation_field",
                        reference="recommendation_type",
                        description=payload.recommendation_output.recommendation_type,
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary=(
                "The incident action stub is structurally valid, approval-aware, and "
                "justified by the recommendation record."
            ),
            evidence=[
                VerifierEvidence(
                    kind="recommendation_field",
                    reference="recommendation_type",
                    description=payload.recommendation_output.recommendation_type,
                ),
                VerifierEvidence(
                    kind="action_stub_field",
                    reference="action_candidate_type",
                    description=payload.action_stub_output.action_candidate_type,
                ),
            ],
        )
