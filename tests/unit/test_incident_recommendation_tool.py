import pytest

from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.implementations.incident_hypothesis import (
    HypothesisConfidence,
    HypothesisType,
    IncidentHypothesisOutput,
)
from tools.implementations.incident_recommendation import (
    IncidentRecommendationBuilderTool,
    IncidentRecommendationOutput,
    RecommendationApprovalLevel,
    RecommendationType,
)
from tools.models import ToolCall, ToolResultStatus


def _hypothesis_output(hypothesis_type: HypothesisType) -> IncidentHypothesisOutput:
    if hypothesis_type is HypothesisType.DEPLOYMENT_REGRESSION:
        return IncidentHypothesisOutput(
            incident_id="incident-800",
            service="payments-api",
            evidence_snapshot_id="deployment-record-2026-04-01",
            evidence_investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
            hypothesis_type=hypothesis_type,
            evidence_supported=True,
            confidence=HypothesisConfidence.MEDIUM,
            rationale_summary="Deployment evidence supports a regression hypothesis.",
            supporting_evidence_fields=["snapshot_id", "evidence_summary", "observations"],
            unresolved_gaps=["Need rollback confirmation before mitigation."],
            recommended_next_action=(
                "Review the deployment diff and validate rollback options for payments-api."
            ),
            more_investigation_required=True,
        )

    return IncidentHypothesisOutput(
        incident_id="incident-801",
        service="payments-api",
        evidence_snapshot_id="runbook-index-2026-04-01",
        evidence_investigation_target=InvestigationTarget.RUNBOOK,
        hypothesis_type=hypothesis_type,
        evidence_supported=False,
        confidence=HypothesisConfidence.LOW,
        rationale_summary="Current evidence is insufficient to support deployment regression.",
        supporting_evidence_fields=["snapshot_id", "evidence_investigation_target"],
        unresolved_gaps=["Need deployment-specific causal evidence."],
        recommended_next_action=(
            "Inspect additional service-local evidence before asserting deployment regression."
        ),
        more_investigation_required=True,
    )


@pytest.mark.asyncio
async def test_incident_recommendation_tool_builds_supported_recommendation() -> None:
    tool = IncidentRecommendationBuilderTool()
    hypothesis_output = _hypothesis_output(HypothesisType.DEPLOYMENT_REGRESSION)

    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={"hypothesis_output": hypothesis_output.model_dump(mode="json")},
        )
    )
    recommendation_output = IncidentRecommendationOutput.model_validate(result.output)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert (
        recommendation_output.recommendation_type
        is RecommendationType.VALIDATE_RECENT_DEPLOYMENT
    )
    assert (
        recommendation_output.required_approval_level
        is RecommendationApprovalLevel.ONCALL_LEAD
    )


@pytest.mark.asyncio
async def test_incident_recommendation_tool_builds_conservative_recommendation() -> None:
    tool = IncidentRecommendationBuilderTool()
    hypothesis_output = _hypothesis_output(HypothesisType.INSUFFICIENT_EVIDENCE)

    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={"hypothesis_output": hypothesis_output.model_dump(mode="json")},
        )
    )
    recommendation_output = IncidentRecommendationOutput.model_validate(result.output)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert recommendation_output.recommendation_type is RecommendationType.INVESTIGATE_MORE
    assert recommendation_output.required_approval_level is RecommendationApprovalLevel.NONE
