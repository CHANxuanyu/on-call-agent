import pytest

from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.implementations.incident_hypothesis import (
    HypothesisType,
    IncidentHypothesisBuilderTool,
)
from tools.models import ToolCall, ToolResultStatus


def _evidence_output(target: InvestigationTarget, snapshot_id: str) -> EvidenceReadOutput:
    if target is InvestigationTarget.RECENT_DEPLOYMENT:
        return EvidenceReadOutput(
            incident_id="incident-600",
            service="payments-api",
            investigation_target=target,
            snapshot_id=snapshot_id,
            evidence_source="evals/fixtures/evidence_snapshots.json::recent_deployment",
            evidence_summary=(
                "A payments-api deployment completed 12 minutes before the alert and "
                "changed request timeout handling."
            ),
            observations=[
                "payments-api deploy 2026-04-01-1 completed 12 minutes before alert fire time",
                "Deployment diff reduced the downstream request timeout threshold",
            ],
            recommended_next_read_only_action=(
                "Review the deployment diff for payments-api."
            ),
        )

    return EvidenceReadOutput(
        incident_id="incident-601",
        service="payments-api",
        investigation_target=target,
        snapshot_id=snapshot_id,
        evidence_source="evals/fixtures/evidence_snapshots.json::runbook",
        evidence_summary=(
            "The runbook index links payments-api triage to dependency timeout checks."
        ),
        observations=[
            "Runbook section 1 recommends checking recent releases first",
        ],
        recommended_next_read_only_action=(
            "Review the payments-api runbook section for dependency timeout checks."
        ),
    )


@pytest.mark.asyncio
async def test_incident_hypothesis_tool_supports_deployment_regression() -> None:
    tool = IncidentHypothesisBuilderTool()
    evidence_output = _evidence_output(
        InvestigationTarget.RECENT_DEPLOYMENT,
        "deployment-record-2026-04-01",
    )

    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={"evidence_output": evidence_output.model_dump(mode="json")},
        )
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output["hypothesis_type"] == HypothesisType.DEPLOYMENT_REGRESSION
    assert result.output["evidence_supported"] is True


@pytest.mark.asyncio
async def test_incident_hypothesis_tool_returns_insufficient_evidence_for_runbook_bundle(
) -> None:
    tool = IncidentHypothesisBuilderTool()
    evidence_output = _evidence_output(
        InvestigationTarget.RUNBOOK,
        "runbook-index-2026-04-01",
    )

    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={"evidence_output": evidence_output.model_dump(mode="json")},
        )
    )

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.output["hypothesis_type"] == HypothesisType.INSUFFICIENT_EVIDENCE
    assert result.output["evidence_supported"] is False
