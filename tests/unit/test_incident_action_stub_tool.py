import pytest

from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.implementations.incident_action_stub import (
    ActionCandidateType,
    IncidentActionStubBuilderTool,
    IncidentActionStubOutput,
)
from tools.implementations.incident_hypothesis import (
    HypothesisConfidence,
    HypothesisType,
    IncidentHypothesisOutput,
)
from tools.implementations.incident_recommendation import IncidentRecommendationBuilderTool
from tools.models import ToolCall, ToolResultStatus


@pytest.mark.asyncio
async def test_incident_action_stub_tool_builds_approval_gated_candidate() -> None:
    recommendation_tool = IncidentRecommendationBuilderTool()
    hypothesis_output = IncidentHypothesisOutput(
        incident_id="incident-1000",
        service="payments-api",
        evidence_snapshot_id="deployment-record-2026-04-01",
        evidence_investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
        hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
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
    recommendation_result = await recommendation_tool.execute(
        ToolCall(
            name=recommendation_tool.definition.name,
            arguments={"hypothesis_output": hypothesis_output.model_dump(mode="json")},
        )
    )

    tool = IncidentActionStubBuilderTool()
    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={"recommendation_output": recommendation_result.output},
        )
    )
    action_stub_output = IncidentActionStubOutput.model_validate(result.output)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert (
        action_stub_output.action_candidate_type
        is ActionCandidateType.DEPLOYMENT_VALIDATION_CANDIDATE
    )
    assert action_stub_output.approval_gate.approval_required is True


@pytest.mark.asyncio
async def test_incident_action_stub_tool_builds_no_actionable_stub() -> None:
    recommendation_tool = IncidentRecommendationBuilderTool()
    hypothesis_output = IncidentHypothesisOutput(
        incident_id="incident-1001",
        service="payments-api",
        evidence_snapshot_id="runbook-index-2026-04-01",
        evidence_investigation_target=InvestigationTarget.RUNBOOK,
        hypothesis_type=HypothesisType.INSUFFICIENT_EVIDENCE,
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
    recommendation_result = await recommendation_tool.execute(
        ToolCall(
            name=recommendation_tool.definition.name,
            arguments={"hypothesis_output": hypothesis_output.model_dump(mode="json")},
        )
    )

    tool = IncidentActionStubBuilderTool()
    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={"recommendation_output": recommendation_result.output},
        )
    )
    action_stub_output = IncidentActionStubOutput.model_validate(result.output)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert action_stub_output.action_candidate_type is ActionCandidateType.NO_ACTIONABLE_STUB_YET
    assert action_stub_output.approval_gate.approval_required is False
