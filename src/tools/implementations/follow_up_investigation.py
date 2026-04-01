"""Deterministic read-only follow-up investigation tool."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.implementations.incident_triage import IncidentTriageOutput
from tools.models import (
    ToolCall,
    ToolDefinition,
    ToolFailure,
    ToolResult,
    ToolResultStatus,
    ToolRiskLevel,
)


class InvestigationTarget(StrEnum):
    """Supported targets for the narrow follow-up investigation slice."""

    RECENT_DEPLOYMENT = "recent_deployment"
    RUNBOOK = "runbook"
    OWNERSHIP = "ownership"
    PRIMARY_SERVICE_EVIDENCE = "primary_service_evidence"


class FollowUpInvestigationInput(BaseModel):
    """Structured input for the deterministic follow-up investigation tool."""

    model_config = ConfigDict(extra="forbid")

    triage_output: IncidentTriageOutput


class FollowUpInvestigationOutput(BaseModel):
    """Structured investigation focus selected from a triage result."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    investigation_target: InvestigationTarget
    evidence_gap: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    recommended_read_only_action: str = Field(min_length=1)


class InvestigationFocusSelectorTool:
    """Selects one deterministic follow-up investigation target from triage output."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="investigation_focus_selector",
            description=(
                "Select one deterministic read-only investigation target from prior triage output."
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
            payload = FollowUpInvestigationInput.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="invalid_arguments",
                    message=str(exc),
                ),
            )

        investigation_output = self._select_focus(payload.triage_output)
        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output=investigation_output.model_dump(mode="json"),
        )

    def _select_focus(self, triage_output: IncidentTriageOutput) -> FollowUpInvestigationOutput:
        if "Recent deployment context is unavailable." in triage_output.unknowns:
            return FollowUpInvestigationOutput(
                incident_id=triage_output.incident_id,
                service=triage_output.service,
                investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
                evidence_gap="Recent deployment context is unavailable.",
                rationale=(
                    "Deployment context is the first missing input and can quickly confirm or "
                    "rule out a recent change."
                ),
                recommended_read_only_action=(
                    f"Inspect the latest deployment record for {triage_output.service}."
                ),
            )

        if "Runbook reference is unavailable." in triage_output.unknowns:
            return FollowUpInvestigationOutput(
                incident_id=triage_output.incident_id,
                service=triage_output.service,
                investigation_target=InvestigationTarget.RUNBOOK,
                evidence_gap="Runbook reference is unavailable.",
                rationale=(
                    "A runbook lookup is the next safest way to ground the investigation in "
                    "existing operational guidance."
                ),
                recommended_read_only_action=(
                    f"Review the runbook index for {triage_output.service}."
                ),
            )

        if "Ownership metadata is unavailable." in triage_output.unknowns:
            return FollowUpInvestigationOutput(
                incident_id=triage_output.incident_id,
                service=triage_output.service,
                investigation_target=InvestigationTarget.OWNERSHIP,
                evidence_gap="Ownership metadata is unavailable.",
                rationale=(
                    "Ownership data is still missing, so confirming the responsible team is the "
                    "best next read-only action."
                ),
                recommended_read_only_action=(
                    f"Inspect the ownership metadata for {triage_output.service}."
                ),
            )

        return FollowUpInvestigationOutput(
            incident_id=triage_output.incident_id,
            service=triage_output.service,
            investigation_target=InvestigationTarget.PRIMARY_SERVICE_EVIDENCE,
            evidence_gap="No unresolved triage metadata gaps remain.",
            rationale=(
                "The triage record is complete enough that the next read-only step should focus "
                "on primary service evidence."
            ),
            recommended_read_only_action=(
                f"Inspect the latest service evidence for {triage_output.service}."
            ),
        )
