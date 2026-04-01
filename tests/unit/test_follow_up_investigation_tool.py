import pytest

from tools.implementations.follow_up_investigation import (
    FollowUpInvestigationOutput,
    InvestigationFocusSelectorTool,
    InvestigationTarget,
)
from tools.implementations.incident_triage import IncidentSeverity, IncidentTriageOutput
from tools.models import ToolCall, ToolResultStatus


@pytest.mark.asyncio
async def test_investigation_focus_selector_picks_first_missing_context() -> None:
    tool = InvestigationFocusSelectorTool()
    triage_output = IncidentTriageOutput(
        incident_id="incident-200",
        service="payments-api",
        incident_summary="Checkout traffic is degraded.",
        suspected_severity=IncidentSeverity.HIGH,
        suspected_blast_radius="Customer-facing impact is likely centered on payments-api.",
        recommended_next_action="Inspect the latest incident evidence for payments-api.",
        unknowns=[
            "Recent deployment context is unavailable.",
            "Runbook reference is unavailable.",
        ],
    )

    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={"triage_output": triage_output.model_dump(mode="json")},
        )
    )

    investigation_output = FollowUpInvestigationOutput.model_validate(result.output)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert investigation_output.investigation_target is InvestigationTarget.RECENT_DEPLOYMENT
    assert investigation_output.recommended_read_only_action.startswith("Inspect")


@pytest.mark.asyncio
async def test_investigation_focus_selector_falls_back_to_primary_evidence() -> None:
    tool = InvestigationFocusSelectorTool()
    triage_output = IncidentTriageOutput(
        incident_id="incident-201",
        service="payments-api",
        incident_summary="Checkout traffic is degraded.",
        suspected_severity=IncidentSeverity.HIGH,
        suspected_blast_radius="Customer-facing impact is likely centered on payments-api.",
        recommended_next_action="Inspect the latest incident evidence for payments-api.",
        unknowns=[],
    )

    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={"triage_output": triage_output.model_dump(mode="json")},
        )
    )

    investigation_output = FollowUpInvestigationOutput.model_validate(result.output)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert investigation_output.investigation_target is InvestigationTarget.PRIMARY_SERVICE_EVIDENCE
