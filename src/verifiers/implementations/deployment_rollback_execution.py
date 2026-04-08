"""Verifier for the bounded rollback execution slice."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from runtime.models import SyntheticFailure
from tools.implementations.deployment_rollback import DeploymentRollbackExecutionOutput
from tools.implementations.incident_action_stub import (
    ActionCandidateType,
    IncidentActionStubOutput,
)
from verifiers.base import (
    VerifierDefinition,
    VerifierDiagnostic,
    VerifierEvidence,
    VerifierKind,
    VerifierRequest,
    VerifierResult,
    VerifierStatus,
)
from verifiers.contracts import validate_inputs_model, verify_request_name


class RollbackExecutionBranch(StrEnum):
    """Branches available to the rollback execution step."""

    EXECUTE_ROLLBACK = "execute_rollback"
    INSUFFICIENT_STATE = "insufficient_state"


class DeploymentRollbackExecutionVerificationInput(BaseModel):
    """Structured payload verified for the rollback execution step."""

    model_config = ConfigDict(extra="forbid")

    branch: RollbackExecutionBranch
    approval_recorded: bool
    insufficiency_reason: str | None = None
    prior_artifact_failure: SyntheticFailure | None = None
    action_stub_output: IncidentActionStubOutput | None = None
    execution_output: DeploymentRollbackExecutionOutput | None = None


class DeploymentRollbackExecutionVerifier:
    """Verify that the bounded rollback execution stayed within its approval scope."""

    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            kind=VerifierKind.OUTCOME,
            name="deployment_rollback_execution",
            description=(
                "Validate that the rollback execution step either correctly deferred due to "
                "missing approved state or completed one bounded rollback."
            ),
            target_condition=(
                "Rollback execution only runs after approval and records a bounded version "
                "transition."
            ),
        )

    async def verify(self, request: VerifierRequest) -> VerifierResult:
        contract = self._verify_contract(request)
        if isinstance(contract, VerifierResult):
            return contract
        return self._verify_outcome(contract)

    def _verify_contract(
        self,
        request: VerifierRequest,
    ) -> DeploymentRollbackExecutionVerificationInput | VerifierResult:
        name_mismatch = verify_request_name(
            request=request,
            definition=self.definition,
            summary="Verifier request name does not match the rollback execution verifier.",
        )
        if name_mismatch is not None:
            return name_mismatch

        return validate_inputs_model(
            request=request,
            model=DeploymentRollbackExecutionVerificationInput,
            summary="Rollback execution verification inputs do not match the expected schema.",
            diagnostic_code="invalid_rollback_execution_inputs",
            retry_reason="Repair the rollback execution verification payload before retrying.",
        )

    def _verify_outcome(
        self,
        payload: DeploymentRollbackExecutionVerificationInput,
    ) -> VerifierResult:
        if payload.branch is RollbackExecutionBranch.INSUFFICIENT_STATE:
            return self._verify_insufficient_state(payload)
        return self._verify_execution(payload)

    def _verify_insufficient_state(
        self,
        payload: DeploymentRollbackExecutionVerificationInput,
    ) -> VerifierResult:
        if payload.execution_output is not None:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary="Insufficient-state rollback branch cannot include an execution output.",
                diagnostics=[
                    VerifierDiagnostic(
                        code="unexpected_execution_output",
                        message="execution_output must be absent for insufficient-state branch",
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary=(
                "Rollback execution correctly deferred because approval or artifacts were not "
                "ready for a bounded write action."
            ),
            evidence=[
                VerifierEvidence(
                    kind="reason",
                    reference="insufficiency_reason",
                    description=payload.insufficiency_reason,
                )
            ],
            diagnostics=(
                [
                    VerifierDiagnostic(
                        code=payload.prior_artifact_failure.code.value,
                        message=payload.prior_artifact_failure.reason,
                    )
                ]
                if payload.prior_artifact_failure is not None
                else []
            ),
        )

    def _verify_execution(
        self,
        payload: DeploymentRollbackExecutionVerificationInput,
    ) -> VerifierResult:
        if payload.action_stub_output is None or payload.execution_output is None:
            return VerifierResult(
                status=VerifierStatus.UNVERIFIED,
                summary=(
                    "Rollback execution branch requires both the consumed action stub and "
                    "the structured execution output."
                ),
                diagnostics=[
                    VerifierDiagnostic(
                        code="missing_execution_inputs",
                        message="action_stub_output and execution_output are required",
                    )
                ],
                retry_hint=VerifierRetryHint(
                    should_retry=False,
                    reason="Provide both action stub and execution output before retrying.",
                ),
            )

        diagnostics: list[VerifierDiagnostic] = []
        if not payload.approval_recorded:
            diagnostics.append(
                VerifierDiagnostic(
                    code="approval_not_recorded",
                    message="rollback execution must not run before approval is recorded",
                )
            )
        if (
            payload.action_stub_output.action_candidate_type
            is not ActionCandidateType.ROLLBACK_RECENT_DEPLOYMENT_CANDIDATE
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_action_candidate_type",
                    message="rollback execution requires the rollback action candidate type",
                )
            )
        if not payload.execution_output.rollback_applied:
            diagnostics.append(
                VerifierDiagnostic(
                    code="rollback_not_applied",
                    message="execution output must report rollback_applied=true",
                )
            )
        if (
            payload.execution_output.observed_version_before
            == payload.execution_output.observed_version_after
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="version_not_changed",
                    message="rollback execution must change the deployed version",
                )
            )
        if (
            payload.execution_output.expected_previous_version is not None
            and payload.execution_output.observed_version_after
            != payload.execution_output.expected_previous_version
        ):
            diagnostics.append(
                VerifierDiagnostic(
                    code="unexpected_post_rollback_version",
                    message=(
                        "post-rollback version does not match the expected previous version"
                    ),
                )
            )

        if diagnostics:
            return VerifierResult(
                status=VerifierStatus.FAIL,
                summary="The rollback execution output is not valid for this bounded slice.",
                diagnostics=diagnostics,
                evidence=[
                    VerifierEvidence(
                        kind="execution_field",
                        reference="observed_version_after",
                        description=payload.execution_output.observed_version_after,
                    )
                ],
            )

        return VerifierResult(
            status=VerifierStatus.PASS,
            summary="Rollback execution stayed within its approved bounded action scope.",
            evidence=[
                VerifierEvidence(
                    kind="execution_field",
                    reference="observed_version_before",
                    description=payload.execution_output.observed_version_before,
                ),
                VerifierEvidence(
                    kind="execution_field",
                    reference="observed_version_after",
                    description=payload.execution_output.observed_version_after,
                ),
            ],
        )
