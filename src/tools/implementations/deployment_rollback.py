"""Bounded rollback tool for the live deployment-regression slice."""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from runtime.demo_target import (
    DemoServiceDeploymentResponse,
    DemoServiceHealthResponse,
    DemoServiceRollbackResponse,
)
from tools.implementations.incident_action_stub import (
    ActionCandidateType,
    IncidentActionStubOutput,
)
from tools.models import (
    ToolCall,
    ToolDefinition,
    ToolFailure,
    ToolResult,
    ToolResultStatus,
    ToolRiskLevel,
)


class DeploymentRollbackInput(BaseModel):
    """Structured input for the bounded rollback tool."""

    model_config = ConfigDict(extra="forbid")

    action_stub_output: IncidentActionStubOutput
    service_base_url: str = Field(min_length=1)
    expected_bad_version: str | None = Field(default=None, min_length=1)
    expected_previous_version: str | None = Field(default=None, min_length=1)


class DeploymentRollbackExecutionOutput(BaseModel):
    """Structured result emitted after a bounded rollback attempt."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    service_base_url: str = Field(min_length=1)
    action_candidate_type: ActionCandidateType
    rollback_applied: bool
    observed_version_before: str = Field(min_length=1)
    observed_version_after: str = Field(min_length=1)
    expected_bad_version: str | None = None
    expected_previous_version: str | None = None
    health_status_before: str = Field(min_length=1)
    health_status_after: str = Field(min_length=1)
    execution_summary: str = Field(min_length=1)
    safety_notes: list[str] = Field(min_length=1)


class DeploymentRollbackExecutorTool:
    """Execute one bounded rollback against the live demo target."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="deployment_rollback_executor",
            description=(
                "Execute a bounded rollback of the current deployment for the live "
                "deployment-regression demo target."
            ),
            risk_level=ToolRiskLevel.WRITE,
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
            payload = DeploymentRollbackInput.model_validate(call.arguments)
            output = await self._execute_bounded_rollback(payload)
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
                    code="rollback_execution_failed",
                    message=str(exc),
                ),
            )

        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output=output.model_dump(mode="json"),
        )

    async def _execute_bounded_rollback(
        self,
        payload: DeploymentRollbackInput,
    ) -> DeploymentRollbackExecutionOutput:
        if (
            payload.action_stub_output.action_candidate_type
            is not ActionCandidateType.ROLLBACK_RECENT_DEPLOYMENT_CANDIDATE
        ):
            msg = "bounded rollback execution requires a rollback_recent_deployment_candidate"
            raise ValueError(msg)

        base_url = payload.service_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=5.0) as client:
            deployment_before_response = await client.get(f"{base_url}/deployment")
            deployment_before_response.raise_for_status()
            health_before_response = await client.get(f"{base_url}/health")
            if health_before_response.status_code not in {
                httpx.codes.OK,
                httpx.codes.SERVICE_UNAVAILABLE,
            }:
                msg = (
                    f"health endpoint returned unexpected status "
                    f"{health_before_response.status_code} for {base_url}"
                )
                raise ValueError(msg)

            deployment_before = DemoServiceDeploymentResponse.model_validate(
                deployment_before_response.json()
            )
            health_before = DemoServiceHealthResponse.model_validate(
                health_before_response.json()
            )
            self._validate_preconditions(
                deployment_before=deployment_before,
                payload=payload,
            )

            rollback_response = await client.post(f"{base_url}/rollback")
            rollback_response.raise_for_status()
            rollback_result = DemoServiceRollbackResponse.model_validate(rollback_response.json())

            deployment_after_response = await client.get(f"{base_url}/deployment")
            deployment_after_response.raise_for_status()
            health_after_response = await client.get(f"{base_url}/health")
            if health_after_response.status_code not in {
                httpx.codes.OK,
                httpx.codes.SERVICE_UNAVAILABLE,
            }:
                msg = (
                    f"health endpoint returned unexpected status "
                    f"{health_after_response.status_code} after rollback for {base_url}"
                )
                raise ValueError(msg)
            deployment_after = DemoServiceDeploymentResponse.model_validate(
                deployment_after_response.json()
            )
            health_after = DemoServiceHealthResponse.model_validate(
                health_after_response.json()
            )

        return DeploymentRollbackExecutionOutput(
            incident_id=payload.action_stub_output.incident_id,
            service=payload.action_stub_output.service,
            service_base_url=payload.service_base_url,
            action_candidate_type=payload.action_stub_output.action_candidate_type,
            rollback_applied=rollback_result.rollback_applied,
            observed_version_before=deployment_before.current_version,
            observed_version_after=deployment_after.current_version,
            expected_bad_version=payload.expected_bad_version,
            expected_previous_version=payload.expected_previous_version,
            health_status_before=health_before.status,
            health_status_after=health_after.status,
            execution_summary=rollback_result.summary,
            safety_notes=[
                "Rollback executed only after explicit approval was recorded.",
                "Rollback target remained bounded to the previous known-good version.",
                (
                    "Live post-action verification is still required before calling the "
                    "incident resolved."
                ),
            ],
        )

    def _validate_preconditions(
        self,
        *,
        deployment_before: DemoServiceDeploymentResponse,
        payload: DeploymentRollbackInput,
    ) -> None:
        if not deployment_before.bad_release_active or not deployment_before.rollback_available:
            msg = (
                "rollback preconditions failed because the deployment endpoint does not report "
                "an active bad release with rollback_available=true"
            )
            raise ValueError(msg)
        if (
            payload.expected_bad_version is not None
            and deployment_before.current_version != payload.expected_bad_version
        ):
            msg = (
                f"rollback refused because current_version '{deployment_before.current_version}' "
                f"does not match expected_bad_version '{payload.expected_bad_version}'"
            )
            raise ValueError(msg)
        if (
            payload.expected_previous_version is not None
            and deployment_before.previous_version != payload.expected_previous_version
        ):
            msg = (
                "rollback refused because the reported previous version "
                f"'{deployment_before.previous_version}' does not match "
                f"expected_previous_version '{payload.expected_previous_version}'"
            )
            raise ValueError(msg)
