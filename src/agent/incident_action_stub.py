"""Resumable approval-gated action stub step built on recommendation artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AgentStatus
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import (
    ApprovalState,
    ApprovalStatus,
    SessionCheckpoint,
)
from permissions.models import PermissionDecision
from permissions.policy import PermissionPolicy
from runtime.harness import (
    ResumableSliceHarness,
    combine_artifact_failure,
    pending_verifier_for_status,
)
from runtime.models import SyntheticFailure
from tools.implementations.incident_action_stub import (
    IncidentActionStubBuilderTool,
    IncidentActionStubOutput,
    action_candidate_requires_approval,
)
from tools.implementations.incident_recommendation import (
    IncidentRecommendationOutput,
    RecommendationType,
)
from tools.models import ToolCall, ToolResult
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus
from verifiers.implementations.incident_action_stub import (
    ActionStubBranch,
    IncidentActionStubOutcomeVerifier,
)


class ActionStubResumeArtifacts(BaseModel):
    """Durable artifacts consulted by the action-stub step."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_path: Path
    transcript_path: Path
    previous_checkpoint_id: str
    previous_phase: str
    prior_transcript_event_count: int
    recommendation_verifier_passed: bool


class IncidentActionStubStepRequest(BaseModel):
    """Structured input for the action-stub continuation step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    resume_reason: str = "Continue from the latest incident-recommendation artifacts."


class IncidentActionStubStepResult(BaseModel):
    """Structured result returned by the action-stub step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    incident_id: str
    resumed_successfully: bool
    branch: ActionStubBranch
    consulted_artifacts: ActionStubResumeArtifacts
    consumed_recommendation_output: IncidentRecommendationOutput | None = None
    action_stub_action_name: str | None = None
    action_candidate_produced: bool | None = None
    approval_required: bool | None = None
    verifier_name: str
    runner_status: AgentStatus
    recommendation_supported: bool | None = None
    conservative_due_to_insufficient_evidence: bool | None = None
    more_follow_up_required: bool
    future_non_read_only_action_blocked_pending_approval: bool | None = None
    verifier_result: VerifierResult
    permission_decision: PermissionDecision | None = None
    tool_result: ToolResult | None = None
    action_stub_output: IncidentActionStubOutput | None = None
    artifact_failure: SyntheticFailure | None = None
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    insufficiency_reason: str | None = None


@dataclass(slots=True)
class _ActionStubResumeContext:
    harness: ResumableSliceHarness
    artifact_context: SessionArtifactContext
    recommendation_output: IncidentRecommendationOutput | None
    recommendation_verifier_passed: bool
    recommendation_failure: SyntheticFailure | None = None
    recommendation_insufficiency_reason: str | None = None


@dataclass(slots=True)
class IncidentActionStubStep:
    """Consumes one recommendation record and builds one approval-aware action stub."""

    transcript_root: Path = Path("sessions/transcripts")
    checkpoint_root: Path = Path("sessions/checkpoints")
    tool: IncidentActionStubBuilderTool = field(default_factory=IncidentActionStubBuilderTool)
    verifier: IncidentActionStubOutcomeVerifier = field(
        default_factory=IncidentActionStubOutcomeVerifier
    )
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)

    async def run(
        self,
        request: IncidentActionStubStepRequest,
    ) -> IncidentActionStubStepResult:
        context = self._load_context(request.session_id)
        harness = context.harness
        step_index = harness.step_index

        harness.emit_resume_started(reason=request.resume_reason)

        branch, insufficiency_reason = self._select_branch(context)
        recommendation_output = context.recommendation_output
        harness.emit_model_step(
            summary=self._model_step_summary(branch, context, recommendation_output),
            planned_verifiers=[self.verifier.definition.name],
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        action_stub_output: IncidentActionStubOutput | None = None

        if branch is ActionStubBranch.BUILD_ACTION_STUB:
            if recommendation_output is None:
                msg = "action-stub branch requires a durable recommendation record"
                raise RuntimeError(msg)

            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={
                    "recommendation_output": recommendation_output.model_dump(mode="json")
                },
            )
            tool_outcome = await harness.execute_read_only_tool(
                tool=self.tool,
                permission_policy=self.permission_policy,
                tool_call=tool_call,
                call_id=f"{request.session_id}-incident-action-stub-tool",
                output_model=IncidentActionStubOutput,
                permission_denied_message=(
                    "incident action stub tool must remain read-only and allowed by default"
                ),
            )
            permission_decision = tool_outcome.permission_decision
            tool_result = tool_outcome.tool_result
            action_stub_output = tool_outcome.output

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.artifact_context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "recommendation_phase": context.artifact_context.checkpoint.current_phase,
                "recommendation_verifier_passed": context.recommendation_verifier_passed,
                "insufficiency_reason": insufficiency_reason,
                "prior_artifact_failure": (
                    context.recommendation_failure.model_dump(mode="json")
                    if context.recommendation_failure is not None
                    else None
                ),
                "recommendation_output": (
                    recommendation_output.model_dump(mode="json")
                    if recommendation_output is not None
                    else None
                ),
                "action_stub_output": (
                    action_stub_output.model_dump(mode="json")
                    if action_stub_output is not None
                    else None
                ),
            },
        )
        verifier_result = await harness.execute_verifier(
            verifier=self.verifier,
            request=verifier_request,
        )
        artifact_failure = combine_artifact_failure(
            prior_failure=context.recommendation_failure,
            tool_result=tool_result,
            verifier_result=verifier_result,
        )

        checkpoint = SessionCheckpoint(
            checkpoint_id=f"{request.session_id}-incident-action-stub",
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            current_phase=self._current_phase(
                branch=branch,
                verifier_status=verifier_result.status,
                action_stub_output=action_stub_output,
                artifact_failure=artifact_failure,
            ),
            current_step=step_index,
            selected_skills=context.artifact_context.checkpoint.selected_skills,
            pending_verifier=pending_verifier_for_status(
                verifier_name=self.verifier.definition.name,
                verifier_request=verifier_request,
                verifier_status=verifier_result.status,
            ),
            approval_state=self._approval_state(
                action_stub_output,
                artifact_failure,
                insufficiency_reason,
            ),
            summary_of_progress=self._progress_summary(
                branch=branch,
                action_stub_output=action_stub_output,
                verifier_result=verifier_result,
                insufficiency_reason=insufficiency_reason,
                artifact_failure=artifact_failure,
            ),
        )
        harness.write_checkpoint(checkpoint)

        return IncidentActionStubStepResult(
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            resumed_successfully=branch is ActionStubBranch.BUILD_ACTION_STUB,
            branch=branch,
            consulted_artifacts=ActionStubResumeArtifacts(
                checkpoint_path=context.artifact_context.checkpoint_path,
                transcript_path=context.artifact_context.transcript_path,
                previous_checkpoint_id=context.artifact_context.checkpoint.checkpoint_id,
                previous_phase=context.artifact_context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.artifact_context.transcript_events),
                recommendation_verifier_passed=context.recommendation_verifier_passed,
            ),
            consumed_recommendation_output=recommendation_output,
            action_stub_action_name=(
                self.tool.definition.name if branch is ActionStubBranch.BUILD_ACTION_STUB else None
            ),
            action_candidate_produced=(
                action_stub_output.action_candidate_created
                if action_stub_output is not None
                else None
            ),
            approval_required=(
                action_candidate_requires_approval(action_stub_output)
                if action_stub_output is not None
                else None
            ),
            verifier_name=self.verifier.definition.name,
            runner_status=self._runner_status(
                branch,
                verifier_result.status,
                action_stub_output,
                artifact_failure,
            ),
            recommendation_supported=(
                recommendation_output.recommendation_type
                is RecommendationType.VALIDATE_RECENT_DEPLOYMENT
                if recommendation_output is not None
                else None
            ),
            conservative_due_to_insufficient_evidence=(
                recommendation_output.recommendation_type is RecommendationType.INVESTIGATE_MORE
                if recommendation_output is not None
                else None
            ),
            more_follow_up_required=True,
            future_non_read_only_action_blocked_pending_approval=(
                action_stub_output.future_non_read_only_action_blocked_pending_approval
                if action_stub_output is not None
                else None
            ),
            verifier_result=verifier_result,
            permission_decision=permission_decision,
            tool_result=tool_result,
            action_stub_output=action_stub_output,
            artifact_failure=artifact_failure,
            checkpoint_path=context.artifact_context.checkpoint_path,
            checkpoint=checkpoint,
            insufficiency_reason=insufficiency_reason,
        )

    def _load_context(self, session_id: str) -> _ActionStubResumeContext:
        harness = ResumableSliceHarness.load(
            session_id=session_id,
            step_name="incident_action_stub",
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
        )
        artifact_context = harness.artifact_context
        recommendation_resolution = artifact_context.recommendation_output_for_action_stub_step()
        recommendation_record = artifact_context.latest_recommendation_output()
        return _ActionStubResumeContext(
            harness=harness,
            artifact_context=artifact_context,
            recommendation_output=recommendation_resolution.artifact,
            recommendation_verifier_passed=(
                recommendation_record.verifier_status is VerifierStatus.PASS
            ),
            recommendation_failure=recommendation_resolution.failure,
            recommendation_insufficiency_reason=recommendation_resolution.reason,
        )

    def _select_branch(
        self,
        context: _ActionStubResumeContext,
    ) -> tuple[ActionStubBranch, str | None]:
        if context.recommendation_output is not None:
            return ActionStubBranch.BUILD_ACTION_STUB, None
        return (
            ActionStubBranch.INSUFFICIENT_STATE,
            context.recommendation_insufficiency_reason
            or "Prior artifacts do not yet contain a verified recommendation record.",
        )

    def _model_step_summary(
        self,
        branch: ActionStubBranch,
        context: _ActionStubResumeContext,
        recommendation_output: IncidentRecommendationOutput | None,
    ) -> str:
        if branch is ActionStubBranch.BUILD_ACTION_STUB and recommendation_output is not None:
            return (
                f"Resume recovered recommendation {recommendation_output.recommendation_type} "
                "from durable artifacts and will build one approval-aware action stub."
            )
        if context.recommendation_failure is not None:
            return (
                "Resume found a structured recommendation artifact failure in phase "
                f"{context.artifact_context.checkpoint.current_phase}, so the action-stub step "
                "will record a failure-aware insufficient-state branch."
            )
        return (
            "Resume did not find a usable verified recommendation record in phase "
            f"{context.artifact_context.checkpoint.current_phase}, so the "
            "action-stub step will record "
            "an insufficient-state branch."
        )

    def _current_phase(
        self,
        branch: ActionStubBranch,
        verifier_status: VerifierStatus,
        action_stub_output: IncidentActionStubOutput | None,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return "action_stub_failed_artifacts"
        if verifier_status is VerifierStatus.UNVERIFIED:
            return "action_stub_unverified"
        if verifier_status is VerifierStatus.FAIL:
            return "action_stub_failed_verification"
        if branch is ActionStubBranch.INSUFFICIENT_STATE:
            return "action_stub_deferred"
        if action_stub_output is None:
            return "action_stub_unverified"
        if action_stub_output.action_candidate_created:
            return "action_stub_pending_approval"
        return "action_stub_not_actionable"

    def _approval_state(
        self,
        action_stub_output: IncidentActionStubOutput | None,
        artifact_failure: SyntheticFailure | None,
        insufficiency_reason: str | None,
    ) -> ApprovalState:
        if artifact_failure is not None:
            return ApprovalState(
                status=ApprovalStatus.NONE,
                reason=artifact_failure.reason,
            )
        if action_stub_output is None:
            return ApprovalState(
                status=ApprovalStatus.NONE,
                reason=insufficiency_reason,
            )
        if action_stub_output.approval_gate.approval_required:
            return ApprovalState(
                status=ApprovalStatus.PENDING,
                requested_action=action_stub_output.action_candidate_type,
                reason=action_stub_output.approval_gate.approval_reason,
                future_preconditions=action_stub_output.approval_gate.future_preconditions,
            )
        return ApprovalState(
            status=ApprovalStatus.NONE,
            reason=action_stub_output.approval_gate.conservative_reason,
            future_preconditions=action_stub_output.approval_gate.future_preconditions,
        )

    def _progress_summary(
        self,
        branch: ActionStubBranch,
        action_stub_output: IncidentActionStubOutput | None,
        verifier_result: VerifierResult,
        insufficiency_reason: str | None,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return (
                "Action-stub step encountered a structured artifact failure: "
                f"{artifact_failure.reason} Verifier status: {verifier_result.status}."
            )
        if branch is ActionStubBranch.INSUFFICIENT_STATE:
            return (
                f"Action-stub step deferred. Reason: {insufficiency_reason} "
                f"Verifier status: {verifier_result.status}."
            )
        if action_stub_output is None:
            return (
                "Action-stub step did not produce a structured action stub. "
                f"Verifier status: {verifier_result.status}."
            )
        return (
            f"Action-stub step produced {action_stub_output.action_candidate_type} for "
            f"{action_stub_output.service}. Verifier status: {verifier_result.status}."
        )

    def _runner_status(
        self,
        branch: ActionStubBranch,
        verifier_status: VerifierStatus,
        action_stub_output: IncidentActionStubOutput | None,
        artifact_failure: SyntheticFailure | None,
    ) -> AgentStatus:
        if artifact_failure is not None:
            return AgentStatus.FAILED
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        if verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if branch is ActionStubBranch.INSUFFICIENT_STATE:
            return AgentStatus.VERIFYING
        if action_stub_output is not None and action_stub_output.action_candidate_created:
            return AgentStatus.WAITING_FOR_APPROVAL
        return AgentStatus.RUNNING
