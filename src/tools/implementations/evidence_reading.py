"""Deterministic evidence-reading tool backed by local fixture data."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from runtime.demo_target import (
    DemoServiceDeploymentResponse,
    DemoServiceHealthResponse,
    DemoServiceMetricsResponse,
)
from tools.implementations.follow_up_investigation import (
    FollowUpInvestigationOutput,
    InvestigationTarget,
)
from tools.implementations.incident_triage import IncidentTriageInput
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
    triage_input: IncidentTriageInput | None = None


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
    """Reads either a live deployment snapshot or a local fixture for a selected target."""

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
                "Read one live or fixture-backed evidence bundle for a previously selected "
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
        except ValidationError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="invalid_arguments",
                    message=str(exc),
                ),
            )
        try:
            if self._should_read_live_evidence(payload):
                evidence_output = await self._read_live_deployment_evidence(payload)
            else:
                evidence_output = self._read_fixture_evidence(payload)
        except FileNotFoundError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="missing_fixture",
                    message=str(exc),
                ),
            )
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="live_evidence_unavailable",
                    message=str(exc),
                ),
            )
        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output=evidence_output.model_dump(mode="json"),
        )

    def _should_read_live_evidence(self, payload: EvidenceReadInput) -> bool:
        return (
            payload.triage_input is not None
            and payload.triage_input.service_base_url is not None
            and payload.investigation_output.investigation_target
            is InvestigationTarget.RECENT_DEPLOYMENT
        )

    def _read_fixture_evidence(self, payload: EvidenceReadInput) -> EvidenceReadOutput:
        snapshot_catalog = self._load_snapshot_catalog()
        snapshot = snapshot_catalog.get(payload.investigation_output.investigation_target)
        if snapshot is None:
            msg = (
                "no evidence snapshot fixture exists for target "
                f"'{payload.investigation_output.investigation_target}'"
            )
            raise ValueError(msg)
        return EvidenceReadOutput(
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

    async def _read_live_deployment_evidence(
        self,
        payload: EvidenceReadInput,
    ) -> EvidenceReadOutput:
        triage_input = payload.triage_input
        if triage_input is None or triage_input.service_base_url is None:
            msg = "live deployment evidence requires triage_input.service_base_url"
            raise ValueError(msg)

        base_url = triage_input.service_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=5.0) as client:
            deployment_response = await client.get(f"{base_url}/deployment")
            deployment_response.raise_for_status()
            metrics_response = await client.get(f"{base_url}/metrics")
            metrics_response.raise_for_status()
            health_response = await client.get(f"{base_url}/health")

        if health_response.status_code not in {
            httpx.codes.OK,
            httpx.codes.SERVICE_UNAVAILABLE,
        }:
            msg = (
                f"health endpoint returned unexpected status {health_response.status_code} "
                f"for {base_url}"
            )
            raise ValueError(msg)

        deployment = DemoServiceDeploymentResponse.model_validate(deployment_response.json())
        metrics = DemoServiceMetricsResponse.model_validate(metrics_response.json())
        health = DemoServiceHealthResponse.model_validate(health_response.json())

        health_summary = (
            "service is healthy"
            if health.healthy
            else (
                f"service is degraded with {health.degraded_reason or 'unknown timeout symptoms'}"
            )
        )
        observations = [
            (
                "Deployment endpoint reports current_version "
                f"{deployment.current_version} and previous_version {deployment.previous_version}."
            ),
            (
                f"Deployment endpoint reports the rollout as recent and before alert triage: "
                f"bad_release_active={deployment.bad_release_active}."
            ),
            (
                f"Health endpoint reports status={health.status}, healthy={health.healthy}, "
                f"error_rate={health.error_rate:.2f}."
            ),
            (
                f"Metrics endpoint reports error_rate={metrics.error_rate:.2f}, "
                f"timeout_rate={metrics.timeout_rate:.2f}, latency_p95_ms={metrics.latency_p95_ms}."
            ),
        ]
        if not health.healthy:
            observations.append(
                "The current deployment correlates with timeout symptoms observed by the runtime."
            )

        return EvidenceReadOutput(
            incident_id=payload.investigation_output.incident_id,
            service=payload.investigation_output.service,
            investigation_target=payload.investigation_output.investigation_target,
            snapshot_id=f"live-deployment-{deployment.current_version}",
            evidence_source=(
                f"{base_url}/deployment,{base_url}/health,{base_url}/metrics"
            ),
            evidence_summary=(
                f"Live runtime evidence shows deployment {deployment.current_version} as the "
                f"current version for {deployment.service}; {health_summary}. "
                "The deployment endpoint indicates the rollout happened before alert triage."
            ),
            observations=observations,
            recommended_next_read_only_action=(
                f"Inspect rollback preconditions for {payload.investigation_output.service}."
            ),
        )

    def _load_snapshot_catalog(self) -> dict[InvestigationTarget, EvidenceSnapshotSpec]:
        if not self.fixtures_path.exists():
            msg = f"evidence fixture catalog not found: {self.fixtures_path}"
            raise FileNotFoundError(msg)
        payload = json.loads(self.fixtures_path.read_text(encoding="utf-8"))
        return _SNAPSHOT_CATALOG_ADAPTER.validate_python(payload)
