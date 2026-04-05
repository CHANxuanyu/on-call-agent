import pytest

from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.implementations.incident_hypothesis import (
    HypothesisConfidence,
    HypothesisType,
    IncidentHypothesisOutput,
)
from tools.implementations.incident_recommendation import (
    ALREADY_HEALTHY_ON_KNOWN_GOOD_REF,
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


def _recovered_hypothesis_output() -> IncidentHypothesisOutput:
    return IncidentHypothesisOutput(
        incident_id="incident-802",
        service="payments-api",
        evidence_snapshot_id="live-deployment-2.0.9",
        evidence_investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
        hypothesis_type=HypothesisType.INSUFFICIENT_EVIDENCE,
        evidence_supported=False,
        confidence=HypothesisConfidence.LOW,
        rationale_summary=(
            "Live runtime evidence shows payments-api is already healthy on version 2.0.9, "
            "so the bad deployment is not currently active and a rollback candidate is not "
            "justified."
        ),
        supporting_evidence_fields=["snapshot_id", "evidence_summary", "observations"],
        unresolved_gaps=[],
        recommended_next_action=(
            "Inspect the recovered runtime artifacts and continue monitoring before "
            "proposing any mitigation."
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


@pytest.mark.asyncio
async def test_incident_recommendation_tool_builds_resolved_no_action_recommendation() -> None:
    tool = IncidentRecommendationBuilderTool()
    hypothesis_output = _recovered_hypothesis_output()

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
    assert ALREADY_HEALTHY_ON_KNOWN_GOOD_REF in recommendation_output.supporting_artifact_refs
    assert "Prepare no rollback action" in recommendation_output.action_summary
