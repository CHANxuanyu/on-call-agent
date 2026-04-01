import pytest

from tools.implementations.incident_triage import (
    IncidentPayloadSummaryTool,
    IncidentSeverity,
    IncidentTriageOutput,
)
from tools.models import ToolCall, ToolResultStatus


@pytest.mark.asyncio
async def test_incident_payload_summary_tool_returns_structured_triage_output() -> None:
    tool = IncidentPayloadSummaryTool()

    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={
                "incident_id": "incident-100",
                "title": "Elevated 5xx errors on payments-api",
                "service": "payments-api",
                "symptoms": ["spike in 5xx", "checkout requests timing out"],
                "impact_summary": "Customer checkout requests are failing intermittently.",
            },
        )
    )

    triage_output = IncidentTriageOutput.model_validate(result.output)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert triage_output.suspected_severity is IncidentSeverity.HIGH
    assert triage_output.recommended_next_action.startswith("Inspect")
    assert triage_output.unknowns != []


@pytest.mark.asyncio
async def test_incident_payload_summary_tool_rejects_unknown_tool_name() -> None:
    tool = IncidentPayloadSummaryTool()

    result = await tool.execute(
        ToolCall(
            name="different_tool",
            arguments={},
        )
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.code == "unknown_tool"
