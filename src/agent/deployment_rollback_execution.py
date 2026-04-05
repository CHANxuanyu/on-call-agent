"""Resumable bounded rollback execution step for the live deployment-regression slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AgentStatus
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import ApprovalStatus, SessionCheckpoint
from permissions.models import PermissionAction, PermissionDecision
from permissions.policy import PermissionPolicy
from runtime.execution import execute_tool_with_invariants, normalize_tool_output
from runtime.harness import (
    ResumableSliceHarness,
    combine_artifact_failure,
    pending_verifier_for_status,
)
from runtime.models import SyntheticFailure
from tools.implementations.deployment_rollback import (
    DeploymentRollbackExecutionOutput,
    DeploymentRollbackExecutorTool,
)
from tools.implementations.incident_action_stub import IncidentActionStubOutput
from tools.implementations.incident_triage import IncidentTriageInput
from tools.models import ToolCall, ToolResult
from transcripts.models import PermissionDecisionEvent, ToolRequestEvent, ToolResultEvent
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus
from verifiers.implementations.deployment_rollback_execution import (
    DeploymentRollbackExecutionVerifier,
    RollbackExecutionBranch,
)


class RollbackExecutionResumeArtifacts(BaseModel):
    """Durable artifacts consulted by the rollback execution step."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_path: Path
    transcript_path: Path
    previous_checkpoint_id: str
    previous_phase: str
    prior_transcript_event_count: int
    approval_recorded: bool


class DeploymentRollbackExecutionStepRequest(BaseModel):
    """Structured input for the bounded rollback execution continuation step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    resume_reason: str = "Continue from the approved rollback candidate."


class DeploymentRollbackExecutionStepResult(BaseModel):
    """Structured result returned by the bounded rollback execution step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    incident_id: str
    resumed_successfully: bool
    branch: RollbackExecutionBranch
    consulted_artifacts: RollbackExecutionResumeArtifacts
    verifier_name: str
    runner_status: AgentStatus
    verifier_result: VerifierResult
    permission_decision: PermissionDecision | None = None
    tool_result: ToolResult | None = None
    action_stub_output: IncidentActionStubOutput | None = None
    execution_output: DeploymentRollbackExecutionOutput | None = None
    artifact_failure: SyntheticFailure | None = None
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    insufficiency_reason: str | None = None


@dataclass(slots=True)
class _RollbackExecutionContext:
    harness: ResumableSliceHarness
    artifact_context: SessionArtifactContext
    action_stub_output: IncidentActionStubOutput | None
    triage_input: IncidentTriageInput | None
    approval_recorded: bool
    action_stub_failure: SyntheticFailure | None = None
    action_stub_insufficiency_reason: str | None = None


@dataclass(slots=True)
class DeploymentRollbackExecutionStep:
    """Execute one approval-gated rollback candidate against the live demo target."""

    transcript_root: Path = Path("sessions/transcripts")
    checkpoint_root: Path = Path("sessions/checkpoints")
    tool: DeploymentRollbackExecutorTool = field(default_factory=DeploymentRollbackExecutorTool)
    verifier: DeploymentRollbackExecutionVerifier = field(
        default_factory=DeploymentRollbackExecutionVerifier
    )
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)

    async def run(
        self,
        request: DeploymentRollbackExecutionStepRequest,
    ) -> DeploymentRollbackExecutionStepResult:
        context = self._load_context(request.session_id)
        harness = context.harness
        step_index = harness.step_index

        harness.emit_resume_started(reason=request.resume_reason)

        branch, insufficiency_reason = self._select_branch(context)
        harness.emit_model_step(
            summary=self._model_step_summary(branch, context),
            planned_verifiers=[self.verifier.definition.name],
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        execution_output: DeploymentRollbackExecutionOutput | None = None

        if branch is RollbackExecutionBranch.EXECUTE_ROLLBACK:
            if context.action_stub_output is None or context.triage_input is None:
                msg = "rollback execution requires both action stub output and triage input"
                raise RuntimeError(msg)
            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={
                    "action_stub_output": context.action_stub_output.model_dump(mode="json"),
                    "service_base_url": context.triage_input.service_base_url,
                    "expected_bad_version": context.triage_input.expected_bad_version,
                    "expected_previous_version": context.triage_input.expected_previous_version,
                },
            )
            permission_decision, tool_result, execution_output = await self._execute_approved_tool(
                harness=harness,
                tool_call=tool_call,
                output_model=DeploymentRollbackExecutionOutput,
                session_id=request.session_id,
            )

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.artifact_context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "approval_recorded": context.approval_recorded,
                "insufficiency_reason": insufficiency_reason,
                "prior_artifact_failure": (
                    context.action_stub_failure.model_dump(mode="json")
                    if context.action_stub_failure is not None
                    else None
                ),
                "action_stub_output": (
                    context.action_stub_output.model_dump(mode="json")
                    if context.action_stub_output is not None
                    else None
                ),
                "execution_output": (
                    execution_output.model_dump(mode="json")
                    if execution_output is not None
                    else None
                ),
            },
        )
        verifier_result = await harness.execute_verifier(
            verifier=self.verifier,
            request=verifier_request,
        )
        artifact_failure = combine_artifact_failure(
            prior_failure=context.action_stub_failure,
            tool_result=tool_result,
            verifier_result=verifier_result,
        )

        checkpoint = SessionCheckpoint(
            checkpoint_id=f"{request.session_id}-deployment-rollback-execution",
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            current_phase=self._current_phase(
                branch=branch,
                verifier_status=verifier_result.status,
                artifact_failure=artifact_failure,
            ),
            current_step=step_index,
            selected_skills=context.artifact_context.checkpoint.selected_skills,
            pending_verifier=pending_verifier_for_status(
                verifier_name=self.verifier.definition.name,
                verifier_request=verifier_request,
                verifier_status=verifier_result.status,
            ),
            approval_state=context.artifact_context.checkpoint.approval_state,
            summary_of_progress=self._progress_summary(
                branch=branch,
                execution_output=execution_output,
                verifier_result=verifier_result,
                insufficiency_reason=insufficiency_reason,
                artifact_failure=artifact_failure,
            ),
        )
        harness.write_checkpoint(checkpoint)

        return DeploymentRollbackExecutionStepResult(
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            resumed_successfully=branch is RollbackExecutionBranch.EXECUTE_ROLLBACK,
            branch=branch,
            consulted_artifacts=RollbackExecutionResumeArtifacts(
                checkpoint_path=context.artifact_context.checkpoint_path,
                transcript_path=context.artifact_context.transcript_path,
                previous_checkpoint_id=context.artifact_context.checkpoint.checkpoint_id,
                previous_phase=context.artifact_context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.artifact_context.transcript_events),
                approval_recorded=context.approval_recorded,
            ),
            verifier_name=self.verifier.definition.name,
            runner_status=self._runner_status(verifier_result.status, artifact_failure),
            verifier_result=verifier_result,
            permission_decision=permission_decision,
            tool_result=tool_result,
            action_stub_output=context.action_stub_output,
            execution_output=execution_output,
            artifact_failure=artifact_failure,
            checkpoint_path=context.artifact_context.checkpoint_path,
            checkpoint=checkpoint,
            insufficiency_reason=insufficiency_reason,
        )

    def _load_context(self, session_id: str) -> _RollbackExecutionContext:
        harness = ResumableSliceHarness.load(
            session_id=session_id,
            step_name="deployment_rollback_execution",
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
        )
        artifact_context = harness.artifact_context
        action_stub_resolution = artifact_context.latest_verified_action_stub_output()
        return _RollbackExecutionContext(
            harness=harness,
            artifact_context=artifact_context,
            action_stub_output=action_stub_resolution.artifact,
            triage_input=artifact_context.latest_triage_input(),
            approval_recorded=(
                artifact_context.checkpoint.approval_state.status is ApprovalStatus.APPROVED
            ),
            action_stub_failure=action_stub_resolution.failure,
            action_stub_insufficiency_reason=action_stub_resolution.reason,
        )

    def _select_branch(
        self,
        context: _RollbackExecutionContext,
    ) -> tuple[RollbackExecutionBranch, str | None]:
        if not context.approval_recorded:
            return (
                RollbackExecutionBranch.INSUFFICIENT_STATE,
                "Rollback execution remains blocked until approval is explicitly recorded.",
            )
        if context.action_stub_output is None:
            return (
                RollbackExecutionBranch.INSUFFICIENT_STATE,
                context.action_stub_insufficiency_reason
                or "Prior artifacts do not contain a verified rollback candidate.",
            )
        if context.triage_input is None or context.triage_input.service_base_url is None:
            return (
                RollbackExecutionBranch.INSUFFICIENT_STATE,
                "Rollback execution requires a service_base_url in the original incident payload.",
            )
        return RollbackExecutionBranch.EXECUTE_ROLLBACK, None

    def _model_step_summary(
        self,
        branch: RollbackExecutionBranch,
        context: _RollbackExecutionContext,
    ) -> str:
        if branch is RollbackExecutionBranch.EXECUTE_ROLLBACK:
            return (
                "Approval is recorded and a verified rollback candidate exists, so the runtime "
                "will execute one bounded rollback against the live demo target."
            )
        if not context.approval_recorded:
            return (
                "The rollback candidate is still approval-gated, so the write step will remain "
                "deferred."
            )
        return (
            "Rollback execution could not find the verified artifacts or live target context "
            "needed for a bounded write action, so it will record an insufficient-state branch."
        )

    async def _execute_approved_tool(
        self,
        *,
        harness: ResumableSliceHarness,
        tool_call: ToolCall,
        output_model: type[DeploymentRollbackExecutionOutput],
        session_id: str,
    ) -> tuple[PermissionDecision, ToolResult, DeploymentRollbackExecutionOutput | None]:
        permission_decision = self.permission_policy.decide(
            self.tool.definition,
            notes=[
                "Step 'deployment_rollback_execution' evaluated this tool after approval was "
                "recorded in the session checkpoint."
            ],
        )
        if permission_decision.action is not PermissionAction.ASK:
            msg = "deployment rollback executor must remain approval-gated under the policy"
            raise RuntimeError(msg)

        permission_decision = self._approved_execution_permission_decision(
            permission_decision
        )
        harness.transcript_store.append(
            PermissionDecisionEvent(
                session_id=session_id,
                step_index=harness.step_index,
                decision=permission_decision,
            )
        )

        call_id = f"{session_id}-deployment-rollback-executor"
        harness.transcript_store.append(
            ToolRequestEvent(
                session_id=session_id,
                step_index=harness.step_index,
                call_id=call_id,
                tool_call=tool_call,
            )
        )
        tool_result = await execute_tool_with_invariants(
            step_name="deployment_rollback_execution",
            tool_name=self.tool.definition.name,
            execute=lambda: self.tool.execute(tool_call),
        )
        tool_result, output = normalize_tool_output(
            step_name="deployment_rollback_execution",
            tool_name=self.tool.definition.name,
            tool_result=tool_result,
            output_model=output_model,
        )
        harness.transcript_store.append(
            ToolResultEvent(
                session_id=session_id,
                step_index=harness.step_index,
                call_id=call_id,
                tool_name=self.tool.definition.name,
                result=tool_result,
            )
        )
        return permission_decision, tool_result, output

    def _approved_execution_permission_decision(
        self,
        permission_decision: PermissionDecision,
    ) -> PermissionDecision:
        provenance = permission_decision.provenance.model_copy(
            update={
                "approval_reason": (
                    "The tool remains approval-gated by policy. Approval was already "
                    "recorded earlier in the session, so this execution is proceeding "
                    "within the reviewed rollback scope."
                ),
                "future_preconditions": [
                    *permission_decision.provenance.future_preconditions,
                    "Approval is already recorded for this session before execution begins.",
                    "Execution must stay bounded to the reviewed rollback target and demo "
                    "service scope.",
                ],
                "notes": [
                    *permission_decision.provenance.notes,
                    "Approval requirement was satisfied by the previously recorded approval "
                    "resolution event.",
                    "This permission record explains policy classification, not a fresh "
                    "request for approval.",
                ],
            }
        )
        return permission_decision.model_copy(
            update={
                "reason": (
                    "write-capable tool remains approval-gated by policy; approval was "
                    "already recorded, so execution proceeds within the reviewed rollback "
                    "scope"
                ),
                "provenance": provenance,
            }
        )

    def _current_phase(
        self,
        *,
        branch: RollbackExecutionBranch,
        verifier_status: VerifierStatus,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return "action_execution_failed_artifacts"
        if verifier_status is VerifierStatus.UNVERIFIED:
            return "action_execution_unverified"
        if verifier_status is VerifierStatus.FAIL:
            return "action_execution_failed_verification"
        if branch is RollbackExecutionBranch.EXECUTE_ROLLBACK:
            return "action_execution_completed"
        return "action_execution_deferred"

    def _progress_summary(
        self,
        *,
        branch: RollbackExecutionBranch,
        execution_output: DeploymentRollbackExecutionOutput | None,
        verifier_result: VerifierResult,
        insufficiency_reason: str | None,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return f"Rollback execution failed due to artifact failure: {artifact_failure.reason}"
        if branch is RollbackExecutionBranch.EXECUTE_ROLLBACK and execution_output is not None:
            return (
                f"Rollback execution changed {execution_output.service} from "
                f"{execution_output.observed_version_before} to "
                f"{execution_output.observed_version_after}. "
                f"Verifier status: {verifier_result.status}."
            )
        return (
            "Rollback execution did not run. "
            f"Reason: {insufficiency_reason or 'insufficient approved state'} "
            f"Verifier status: {verifier_result.status}."
        )

    def _runner_status(
        self,
        verifier_status: VerifierStatus,
        artifact_failure: SyntheticFailure | None,
    ) -> AgentStatus:
        if artifact_failure is not None or verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        return AgentStatus.COMPLETED
