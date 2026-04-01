"""Deterministic evidence-reading tool backed by local fixture data."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from tools.implementations.follow_up_investigation import (
    FollowUpInvestigationOutput,
    InvestigationTarget,
)
from tools.models import (
    ToolCall,
    ToolDefinition,
    ToolFailure,
    ToolResult,
    ToolResultStatus,
    ToolRiskLevel,
)


class EvidenceSnapshotSpec(BaseModel):
    """Fixture-backed evidence snapshot keyed by investigation target."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1)
    evidence_summary: str = Field(min_length=1)
    observations: list[str] = Field(min_length=1)
    recommended_next_read_only_action: str = Field(min_length=1)


class EvidenceReadInput(BaseModel):
    """Structured input for the deterministic evidence reader."""

    model_config = ConfigDict(extra="forbid")

    investigation_output: FollowUpInvestigationOutput


class EvidenceReadOutput(BaseModel):
    """Structured evidence record returned by the evidence-reading slice."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    investigation_target: InvestigationTarget
    snapshot_id: str = Field(min_length=1)
    evidence_source: str = Field(min_length=1)
    evidence_summary: str = Field(min_length=1)
    observations: list[str] = Field(min_length=1)
    recommended_next_read_only_action: str = Field(min_length=1)


_SNAPSHOT_CATALOG_ADAPTER: TypeAdapter[
    dict[InvestigationTarget, EvidenceSnapshotSpec]
] = TypeAdapter(dict[InvestigationTarget, EvidenceSnapshotSpec])


class EvidenceBundleReaderTool:
    """Reads one deterministic local evidence snapshot for a selected target."""

    def __init__(
        self,
        fixtures_path: Path = Path("evals/fixtures/evidence_snapshots.json"),
    ) -> None:
        self.fixtures_path = fixtures_path

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="evidence_bundle_reader",
            description=(
                "Read one deterministic local evidence snapshot for a previously selected "
                "investigation target."
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
            payload = EvidenceReadInput.model_validate(call.arguments)
            snapshot_catalog = self._load_snapshot_catalog()
        except ValidationError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="invalid_arguments",
                    message=str(exc),
                ),
            )
        except FileNotFoundError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="missing_fixture",
                    message=str(exc),
                ),
            )

        snapshot = snapshot_catalog.get(payload.investigation_output.investigation_target)
        if snapshot is None:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="unknown_target_fixture",
                    message=(
                        "no evidence snapshot fixture exists for target "
                        f"'{payload.investigation_output.investigation_target}'"
                    ),
                ),
            )
        evidence_output = EvidenceReadOutput(
            incident_id=payload.investigation_output.incident_id,
            service=payload.investigation_output.service,
            investigation_target=payload.investigation_output.investigation_target,
            snapshot_id=snapshot.snapshot_id,
            evidence_source=(
                f"{self.fixtures_path}::{payload.investigation_output.investigation_target}"
            ),
            evidence_summary=snapshot.evidence_summary,
            observations=snapshot.observations,
            recommended_next_read_only_action=snapshot.recommended_next_read_only_action,
        )
        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output=evidence_output.model_dump(mode="json"),
        )

    def _load_snapshot_catalog(self) -> dict[InvestigationTarget, EvidenceSnapshotSpec]:
        if not self.fixtures_path.exists():
            msg = f"evidence fixture catalog not found: {self.fixtures_path}"
            raise FileNotFoundError(msg)
        payload = json.loads(self.fixtures_path.read_text(encoding="utf-8"))
        return _SNAPSHOT_CATALOG_ADAPTER.validate_python(payload)
