"""Deterministic approval-gated action stub builder."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tools.implementations.incident_recommendation import (
    IncidentRecommendationOutput,
    RecommendationApprovalLevel,
    RecommendationRiskLevel,
    RecommendationType,
)
from tools.models import (
    ToolCall,
    ToolDefinition,
    ToolFailure,
    ToolResult,
    ToolResultStatus,
    ToolRiskLevel,
)


class ActionCandidateType(StrEnum):
    """Supported action-candidate outcomes for the narrow slice."""

    ROLLBACK_RECENT_DEPLOYMENT_CANDIDATE = "rollback_recent_deployment_candidate"
    # Compatibility alias retained for older tests and replay-facing references.
    DEPLOYMENT_VALIDATION_CANDIDATE = "rollback_recent_deployment_candidate"
    NO_ACTIONABLE_STUB_YET = "no_actionable_stub_yet"


class ApprovalGateOutcome(BaseModel):
    """Structured approval decision for a future non-read-only action."""

    model_config = ConfigDict(extra="forbid")

    approval_required: bool
    approval_reason: str = Field(min_length=1)
    proposed_action_type: ActionCandidateType
    allowed_without_approval: bool = False
    approval_level: RecommendationApprovalLevel
    conservative_reason: str | None = None
    future_preconditions: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_gate(self) -> ApprovalGateOutcome:
        """Enforce that this slice remains explicitly non-executing."""

        if self.allowed_without_approval:
            msg = "allowed_without_approval must remain false in this slice"
            raise ValueError(msg)

        if (
            self.proposed_action_type
            is ActionCandidateType.ROLLBACK_RECENT_DEPLOYMENT_CANDIDATE
        ):
            if not self.approval_required:
                msg = "rollback candidate must require approval"
                raise ValueError(msg)
            if self.approval_level is RecommendationApprovalLevel.NONE:
                msg = "approval_level must be non-none when approval is required"
                raise ValueError(msg)
            if self.conservative_reason is not None:
                msg = "actionable candidate cannot carry a conservative_reason"
                raise ValueError(msg)
            return self

        if self.approval_required:
            msg = "no-actionable outcome cannot require approval"
            raise ValueError(msg)
        if self.approval_level is not RecommendationApprovalLevel.NONE:
            msg = "no-actionable outcome must use approval_level none"
            raise ValueError(msg)
        if self.conservative_reason is None:
            msg = "no-actionable outcome requires conservative_reason"
            raise ValueError(msg)
        return self


class IncidentActionStubInput(BaseModel):
    """Structured input for the action-stub builder."""

    model_config = ConfigDict(extra="forbid")

    recommendation_output: IncidentRecommendationOutput


class IncidentActionStubOutput(BaseModel):
    """Structured approval-aware action candidate or no-action outcome."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    consumed_recommendation_type: RecommendationType
    action_candidate_type: ActionCandidateType
    action_candidate_created: bool
    action_summary: str = Field(min_length=1)
    justification: str = Field(min_length=1)
    risk_level: RecommendationRiskLevel
    supporting_artifact_refs: list[str] = Field(min_length=1)
    expected_outcome: str = Field(min_length=1)
    safety_notes: str = Field(min_length=1)
    approval_gate: ApprovalGateOutcome
    future_non_read_only_action_blocked_pending_approval: bool
    more_investigation_required: bool

    @model_validator(mode="after")
    def validate_output(self) -> IncidentActionStubOutput:
        """Keep the action-stub output internally consistent."""

        if self.action_candidate_created:
            if self.action_candidate_type is ActionCandidateType.NO_ACTIONABLE_STUB_YET:
                msg = "created action candidate cannot use no-actionable type"
                raise ValueError(msg)
            if not self.approval_gate.approval_required:
                msg = "created action candidate must remain approval-gated"
                raise ValueError(msg)
            if not self.future_non_read_only_action_blocked_pending_approval:
                msg = "created action candidate must remain blocked pending approval"
                raise ValueError(msg)
            return self

        if self.action_candidate_type is not ActionCandidateType.NO_ACTIONABLE_STUB_YET:
            msg = "no-action outcome must use no_actionable_stub_yet"
            raise ValueError(msg)
        if self.future_non_read_only_action_blocked_pending_approval:
            msg = "no-action outcome cannot be blocked pending approval"
            raise ValueError(msg)
        return self


def action_candidate_requires_approval(
    action_stub_output: IncidentActionStubOutput,
) -> bool:
    """Return whether the action stub remains blocked behind approval."""

    return action_stub_output.approval_gate.approval_required


class IncidentActionStubBuilderTool:
    """Maps one recommendation to one approval-aware action stub."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="incident_action_stub_builder",
            description=(
                "Map one structured recommendation to one deterministic approval-aware "
                "action candidate stub."
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
            payload = IncidentActionStubInput.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="invalid_arguments",
                    message=str(exc),
                ),
            )

        action_stub_output = self._build_action_stub(payload.recommendation_output)
        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output=action_stub_output.model_dump(mode="json"),
        )

    def _build_action_stub(
        self,
        recommendation_output: IncidentRecommendationOutput,
    ) -> IncidentActionStubOutput:
        if (
            recommendation_output.recommendation_type
            is RecommendationType.VALIDATE_RECENT_DEPLOYMENT
            and recommendation_output.required_approval_level
            is not RecommendationApprovalLevel.NONE
        ):
            return IncidentActionStubOutput(
                incident_id=recommendation_output.incident_id,
                service=recommendation_output.service,
                consumed_recommendation_type=recommendation_output.recommendation_type,
                action_candidate_type=(
                    ActionCandidateType.ROLLBACK_RECENT_DEPLOYMENT_CANDIDATE
                ),
                action_candidate_created=True,
                action_summary=(
                    f"Propose a rollback to the previous known-good version for "
                    f"{recommendation_output.service} pending approval."
                ),
                justification=(
                    f"{recommendation_output.justification} This slice records the "
                    "candidate but does not execute it."
                ),
                risk_level=recommendation_output.risk_level,
                supporting_artifact_refs=recommendation_output.supporting_artifact_refs,
                expected_outcome=(
                    f"An approval-ready rollback candidate exists for "
                    f"{recommendation_output.service}."
                ),
                safety_notes=(
                    recommendation_output.rollback_or_safety_notes
                    or "Do not execute non-read-only actions from this stub."
                ),
                approval_gate=ApprovalGateOutcome(
                    approval_required=True,
                    approval_reason=(
                        "The proposed candidate could lead to non-read-only mitigation work "
                        "and must remain blocked pending on-call lead approval."
                    ),
                    proposed_action_type=(
                        ActionCandidateType.ROLLBACK_RECENT_DEPLOYMENT_CANDIDATE
                    ),
                    allowed_without_approval=False,
                    approval_level=recommendation_output.required_approval_level,
                    future_preconditions=[
                        *recommendation_output.preconditions,
                        "Human approval must be recorded before any non-read-only action.",
                    ],
                ),
                future_non_read_only_action_blocked_pending_approval=True,
                more_investigation_required=True,
            )

        return IncidentActionStubOutput(
            incident_id=recommendation_output.incident_id,
            service=recommendation_output.service,
            consumed_recommendation_type=recommendation_output.recommendation_type,
            action_candidate_type=ActionCandidateType.NO_ACTIONABLE_STUB_YET,
            action_candidate_created=False,
            action_summary=(
                f"Continue conservative investigation for {recommendation_output.service}; "
                "no actionable stub should proceed yet."
            ),
            justification=(
                f"{recommendation_output.justification} The current recommendation does "
                "not justify proposing an approval-gated action candidate."
            ),
            risk_level=recommendation_output.risk_level,
            supporting_artifact_refs=recommendation_output.supporting_artifact_refs,
            expected_outcome=(
                "Further read-only evidence is gathered before any action candidate is "
                "proposed."
            ),
            safety_notes=(
                "No non-read-only action candidate should be proposed or executed at the "
                "current evidence quality."
            ),
            approval_gate=ApprovalGateOutcome(
                approval_required=False,
                approval_reason=(
                    "The current recommendation remains conservative and does not justify "
                    "proposing a non-read-only action candidate."
                ),
                proposed_action_type=ActionCandidateType.NO_ACTIONABLE_STUB_YET,
                allowed_without_approval=False,
                approval_level=RecommendationApprovalLevel.NONE,
                conservative_reason=(
                    "The current recommendation stays read-only and advisory because "
                    "evidence remains insufficient."
                ),
                future_preconditions=[
                    *recommendation_output.preconditions,
                    "Stronger causal evidence is required before proposing a "
                    "non-read-only candidate.",
                ],
            ),
            future_non_read_only_action_blocked_pending_approval=False,
            more_investigation_required=True,
        )
