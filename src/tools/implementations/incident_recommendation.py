"""Deterministic recommendation tool built from structured hypotheses."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.implementations.incident_hypothesis import (
    HypothesisType,
    IncidentHypothesisOutput,
)
from tools.models import (
    ToolCall,
    ToolDefinition,
    ToolFailure,
    ToolResult,
    ToolResultStatus,
    ToolRiskLevel,
)


class RecommendationType(StrEnum):
    """Supported recommendation outcomes for the narrow slice."""

    # This serialized value is intentionally stable for replay/eval compatibility.
    # In the live deployment-regression slice it means validating rollback readiness,
    # not yet proposing or executing a rollback.
    VALIDATE_RECENT_DEPLOYMENT = "validate_recent_deployment"
    INVESTIGATE_MORE = "investigate_more"


class RecommendationRiskLevel(StrEnum):
    """Risk buckets for future actions implied by a recommendation."""

    LOW = "low"
    MEDIUM = "medium"


class RecommendationApprovalLevel(StrEnum):
    """Approval requirements for any future non-read-only action."""

    NONE = "none"
    ONCALL_LEAD = "oncall_lead"


class IncidentRecommendationInput(BaseModel):
    """Structured input for the recommendation builder."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_output: IncidentHypothesisOutput


class IncidentRecommendationOutput(BaseModel):
    """Structured next-action recommendation derived from one hypothesis."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    consumed_hypothesis_type: HypothesisType
    recommendation_type: RecommendationType
    action_summary: str = Field(min_length=1)
    justification: str = Field(min_length=1)
    risk_level: RecommendationRiskLevel
    required_approval_level: RecommendationApprovalLevel
    preconditions: list[str] = Field(min_length=1)
    supporting_artifact_refs: list[str] = Field(min_length=1)
    expected_outcome: str = Field(min_length=1)
    rollback_or_safety_notes: str | None = None
    more_investigation_required: bool


def recommendation_requires_approval(
    recommendation_output: IncidentRecommendationOutput,
) -> bool:
    """Return whether the recommendation implies a future approval gate."""

    return (
        recommendation_output.required_approval_level
        is not RecommendationApprovalLevel.NONE
    )


class IncidentRecommendationBuilderTool:
    """Maps one structured hypothesis to one deterministic recommendation."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="incident_recommendation_builder",
            description=(
                "Map one structured incident hypothesis to one deterministic "
                "next-action recommendation."
            ),
            risk_level=ToolRiskLevel.READ_ONLY,
        )

    async def execute(self, call: ToolCall) -> ToolResult:
        if call.name != self.definition.name:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="unknown_tool",
                    message=f"tool call name '{call.name}' does not match '{self.definition.name}'",
                ),
            )

        try:
            payload = IncidentRecommendationInput.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="invalid_arguments",
                    message=str(exc),
                ),
            )

        recommendation_output = self._build_recommendation(payload.hypothesis_output)
        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output=recommendation_output.model_dump(mode="json"),
        )

    def _build_recommendation(
        self,
        hypothesis_output: IncidentHypothesisOutput,
    ) -> IncidentRecommendationOutput:
        supporting_refs = [
            f"hypothesis:{hypothesis_output.hypothesis_type}",
            f"evidence:{hypothesis_output.evidence_snapshot_id}",
        ]
        if (
            hypothesis_output.hypothesis_type is HypothesisType.DEPLOYMENT_REGRESSION
            and hypothesis_output.evidence_supported
        ):
            return IncidentRecommendationOutput(
                incident_id=hypothesis_output.incident_id,
                service=hypothesis_output.service,
                consumed_hypothesis_type=hypothesis_output.hypothesis_type,
                recommendation_type=RecommendationType.VALIDATE_RECENT_DEPLOYMENT,
                action_summary=(
                    f"Validate rollback readiness for the recent deployment on "
                    f"{hypothesis_output.service} and prepare an approval review if "
                    "rollback preconditions hold."
                ),
                justification=(
                    f"{hypothesis_output.rationale_summary} The next action should stay "
                    "at rollback-readiness validation until rollback preconditions are "
                    "explicitly confirmed and an approval review can justify a later "
                    "rollback candidate."
                ),
                risk_level=RecommendationRiskLevel.MEDIUM,
                required_approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
                preconditions=[
                    (
                        "Confirm the currently deployed version still matches the suspected "
                        "bad release."
                    ),
                    "Confirm the previous version is a known-good rollback target.",
                    (
                        "Keep all non-read-only actions blocked until on-call lead approval "
                        "is recorded."
                    ),
                ],
                supporting_artifact_refs=supporting_refs,
                expected_outcome=(
                    f"A verified rollback-readiness assessment can justify a later "
                    f"approval-ready rollback candidate for {hypothesis_output.service}."
                ),
                rollback_or_safety_notes=(
                    "Do not execute rollback or any write action without human approval, "
                    "a version match check, and a bounded rollback safety check."
                ),
                more_investigation_required=True,
            )

        return IncidentRecommendationOutput(
            incident_id=hypothesis_output.incident_id,
            service=hypothesis_output.service,
            consumed_hypothesis_type=hypothesis_output.hypothesis_type,
            recommendation_type=RecommendationType.INVESTIGATE_MORE,
            action_summary=(
                f"Investigate more read-only service evidence before proposing rollback "
                f"or escalation for {hypothesis_output.service}."
            ),
            justification=(
                f"{hypothesis_output.rationale_summary} Continue with read-only evidence "
                "gathering until the deployment hypothesis is better supported."
            ),
            risk_level=RecommendationRiskLevel.LOW,
            required_approval_level=RecommendationApprovalLevel.NONE,
            preconditions=[
                "Keep next actions read-only until deployment-specific causal evidence exists."
            ],
            supporting_artifact_refs=supporting_refs,
            expected_outcome=(
                "Additional evidence clarifies whether deployment regression is plausible."
            ),
            rollback_or_safety_notes=(
                "Avoid proposing rollback or escalation based on the current evidence quality."
            ),
            more_investigation_required=True,
        )
