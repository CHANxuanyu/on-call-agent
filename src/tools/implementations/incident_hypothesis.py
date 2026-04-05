"""Deterministic incident-hypothesis tool built from structured evidence."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.models import (
    ToolCall,
    ToolDefinition,
    ToolFailure,
    ToolResult,
    ToolResultStatus,
    ToolRiskLevel,
)

DEPLOYMENT_REGRESSION_VALIDATION_GAP = (
    "Need rollback or mitigation confirmation before treating the regression as validated."
)


class HypothesisType(StrEnum):
    """Supported primary hypothesis outcomes for the narrow slice."""

    DEPLOYMENT_REGRESSION = "deployment_regression"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class HypothesisConfidence(StrEnum):
    """Confidence buckets for the deterministic hypothesis output."""

    LOW = "low"
    MEDIUM = "medium"


class IncidentHypothesisInput(BaseModel):
    """Structured input for the incident hypothesis tool."""

    model_config = ConfigDict(extra="forbid")

    evidence_output: EvidenceReadOutput


class IncidentHypothesisOutput(BaseModel):
    """Structured primary hypothesis for the current evidence slice."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    evidence_snapshot_id: str = Field(min_length=1)
    evidence_investigation_target: InvestigationTarget
    hypothesis_type: HypothesisType
    evidence_supported: bool
    confidence: HypothesisConfidence
    rationale_summary: str = Field(min_length=1)
    supporting_evidence_fields: list[str] = Field(min_length=1)
    unresolved_gaps: list[str] = Field(default_factory=list)
    recommended_next_action: str = Field(min_length=1)
    more_investigation_required: bool


def evidence_supports_deployment_regression(evidence_output: EvidenceReadOutput) -> bool:
    """Return whether the current evidence bundle supports deployment regression."""

    if evidence_output.investigation_target is not InvestigationTarget.RECENT_DEPLOYMENT:
        return False

    searchable_text = " ".join(
        [evidence_output.evidence_summary, *evidence_output.observations]
    ).lower()
    return all(
        marker in searchable_text
        for marker in ("deploy", "before alert", "timeout")
    )


class IncidentHypothesisBuilderTool:
    """Maps one structured evidence record to one structured hypothesis."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="incident_hypothesis_builder",
            description=(
                "Map one structured evidence record to one deterministic incident "
                "hypothesis."
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
            payload = IncidentHypothesisInput.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="invalid_arguments",
                    message=str(exc),
                ),
            )

        hypothesis_output = self._build_hypothesis(payload.evidence_output)
        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output=hypothesis_output.model_dump(mode="json"),
        )

    def _build_hypothesis(
        self,
        evidence_output: EvidenceReadOutput,
    ) -> IncidentHypothesisOutput:
        if evidence_supports_deployment_regression(evidence_output):
            return IncidentHypothesisOutput(
                incident_id=evidence_output.incident_id,
                service=evidence_output.service,
                evidence_snapshot_id=evidence_output.snapshot_id,
                evidence_investigation_target=evidence_output.investigation_target,
                hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
                evidence_supported=True,
                confidence=HypothesisConfidence.MEDIUM,
                rationale_summary=(
                    f"Evidence from {evidence_output.snapshot_id} supports a recent deployment "
                    f"regression affecting {evidence_output.service}."
                ),
                supporting_evidence_fields=[
                    "snapshot_id",
                    "evidence_summary",
                    "observations",
                ],
                unresolved_gaps=[DEPLOYMENT_REGRESSION_VALIDATION_GAP],
                recommended_next_action=(
                    f"Review the deployment diff and validate rollback options for "
                    f"{evidence_output.service}."
                ),
                more_investigation_required=True,
            )

        return IncidentHypothesisOutput(
            incident_id=evidence_output.incident_id,
            service=evidence_output.service,
            evidence_snapshot_id=evidence_output.snapshot_id,
            evidence_investigation_target=evidence_output.investigation_target,
            hypothesis_type=HypothesisType.INSUFFICIENT_EVIDENCE,
            evidence_supported=False,
            confidence=HypothesisConfidence.LOW,
            rationale_summary=(
                f"Evidence from {evidence_output.snapshot_id} does not directly support a "
                f"deployment regression hypothesis for {evidence_output.service}."
            ),
            supporting_evidence_fields=[
                "snapshot_id",
                "evidence_investigation_target",
            ],
            unresolved_gaps=[
                "Need deployment-specific causal evidence before asserting deployment "
                "regression."
            ],
            recommended_next_action=(
                f"Inspect additional service-local evidence before asserting deployment "
                f"regression for {evidence_output.service}."
            ),
            more_investigation_required=True,
        )
