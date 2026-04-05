"""Deterministic read-only tool for first-pass incident triage."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.models import (
    ToolCall,
    ToolDefinition,
    ToolFailure,
    ToolResult,
    ToolResultStatus,
    ToolRiskLevel,
)


class IncidentSeverity(StrEnum):
    """Supported severity levels for the initial triage slice."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncidentTriageInput(BaseModel):
    """Structured incident input for the read-only triage tool."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    service: str = Field(min_length=1)
    symptoms: list[str] = Field(default_factory=list)
    impact_summary: str = Field(min_length=1)
    severity_hint: IncidentSeverity | None = None
    recent_deployment: str | None = None
    runbook_reference: str | None = None
    ownership_team: str | None = None
    service_base_url: str | None = Field(default=None, min_length=1)
    expected_bad_version: str | None = Field(default=None, min_length=1)
    expected_previous_version: str | None = Field(default=None, min_length=1)


class IncidentTriageOutput(BaseModel):
    """Structured triage result suitable for transcripts and verification."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    incident_summary: str = Field(min_length=1)
    suspected_severity: IncidentSeverity
    suspected_blast_radius: str = Field(min_length=1)
    recommended_next_action: str = Field(min_length=1)
    unknowns: list[str] = Field(default_factory=list)


class IncidentPayloadSummaryTool:
    """Summarizes a structured incident payload into an initial triage record."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="incident_payload_summary",
            description=(
                "Summarize a structured incident payload into a deterministic triage record."
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
            incident = IncidentTriageInput.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="invalid_arguments",
                    message=str(exc),
                ),
            )

        triage_output = IncidentTriageOutput(
            incident_id=incident.incident_id,
            service=incident.service,
            incident_summary=(
                f"{incident.title} affecting {incident.service}. "
                f"Impact: {incident.impact_summary.strip()}"
            ),
            suspected_severity=self._classify_severity(incident),
            suspected_blast_radius=self._classify_blast_radius(incident),
            recommended_next_action=self._recommend_next_action(incident),
            unknowns=self._collect_unknowns(incident),
        )
        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output=triage_output.model_dump(mode="json"),
        )

    def _classify_severity(self, incident: IncidentTriageInput) -> IncidentSeverity:
        if incident.severity_hint is not None:
            return incident.severity_hint

        searchable_text = " ".join(
            [
                incident.title,
                incident.impact_summary,
                *incident.symptoms,
            ]
        ).lower()

        if any(
            marker in searchable_text
            for marker in ("sev1", "critical", "outage", "down", "all requests failing")
        ):
            return IncidentSeverity.CRITICAL
        if any(
            marker in searchable_text
            for marker in ("5xx", "error", "timeout", "latency", "degraded")
        ):
            return IncidentSeverity.HIGH
        if any(marker in searchable_text for marker in ("partial", "intermittent", "warning")):
            return IncidentSeverity.MEDIUM
        return IncidentSeverity.LOW

    def _classify_blast_radius(self, incident: IncidentTriageInput) -> str:
        impact_text = incident.impact_summary.lower()
        if any(marker in impact_text for marker in ("customer", "checkout", "login", "all users")):
            return f"Customer-facing impact is likely centered on {incident.service}."
        if len(incident.symptoms) > 1:
            return f"Multiple signals point to a service-local issue in {incident.service}."
        return f"Impact appears localized to {incident.service} pending further confirmation."

    def _recommend_next_action(self, incident: IncidentTriageInput) -> str:
        if incident.runbook_reference:
            return (
                f"Review runbook {incident.runbook_reference} and inspect the latest incident "
                f"evidence for {incident.service}."
            )
        return f"Inspect the latest incident evidence for {incident.service}."

    def _collect_unknowns(self, incident: IncidentTriageInput) -> list[str]:
        unknowns: list[str] = []
        if incident.recent_deployment is None:
            unknowns.append("Recent deployment context is unavailable.")
        if incident.runbook_reference is None:
            unknowns.append("Runbook reference is unavailable.")
        if incident.ownership_team is None:
            unknowns.append("Ownership metadata is unavailable.")
        return unknowns
