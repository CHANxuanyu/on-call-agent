"""Read-only post-action outcome probe for the live deployment-regression slice."""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from runtime.demo_target import (
    DemoServiceDeploymentResponse,
    DemoServiceHealthResponse,
    DemoServiceMetricsResponse,
)
from tools.models import (
    ToolCall,
    ToolDefinition,
    ToolFailure,
    ToolResult,
    ToolResultStatus,
    ToolRiskLevel,
)


class DeploymentOutcomeProbeInput(BaseModel):
    """Structured input for the post-action outcome probe."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    service_base_url: str = Field(min_length=1)
    expected_previous_version: str | None = Field(default=None, min_length=1)


class DeploymentOutcomeProbeOutput(BaseModel):
    """Structured runtime snapshot used by the post-action verifier."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    service_base_url: str = Field(min_length=1)
    current_version: str = Field(min_length=1)
    expected_previous_version: str | None = None
    health_status: str = Field(min_length=1)
    healthy: bool
    error_rate: float
    timeout_rate: float
    latency_p95_ms: int
    evidence_refs: list[str] = Field(min_length=1)
    summary: str = Field(min_length=1)


class DeploymentOutcomeProbeTool:
    """Collect a fresh post-action runtime snapshot from the live demo target."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="deployment_outcome_probe",
            description=(
                "Probe live health, deployment, and metrics endpoints after a bounded "
                "rollback."
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
            payload = DeploymentOutcomeProbeInput.model_validate(call.arguments)
            output = await self._probe_runtime_state(payload)
        except ValidationError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="invalid_arguments",
                    message=str(exc),
                ),
            )
        except (httpx.HTTPError, ValueError) as exc:
            return ToolResult(
                status=ToolResultStatus.FAILED,
                failure=ToolFailure(
                    code="outcome_probe_failed",
                    message=str(exc),
                ),
            )

        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output=output.model_dump(mode="json"),
        )

    async def _probe_runtime_state(
        self,
        payload: DeploymentOutcomeProbeInput,
    ) -> DeploymentOutcomeProbeOutput:
        base_url = payload.service_base_url.rstrip("/")
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

        return DeploymentOutcomeProbeOutput(
            incident_id=payload.incident_id,
            service=payload.service,
            service_base_url=payload.service_base_url,
            current_version=deployment.current_version,
            expected_previous_version=payload.expected_previous_version,
            health_status=health.status,
            healthy=health.healthy,
            error_rate=metrics.error_rate,
            timeout_rate=metrics.timeout_rate,
            latency_p95_ms=metrics.latency_p95_ms,
            evidence_refs=[
                f"{base_url}/deployment",
                f"{base_url}/health",
                f"{base_url}/metrics",
            ],
            summary=(
                f"Runtime probe sees version {deployment.current_version}, "
                f"health_status={health.status}, error_rate={metrics.error_rate:.2f}, "
                f"timeout_rate={metrics.timeout_rate:.2f}."
            ),
        )
