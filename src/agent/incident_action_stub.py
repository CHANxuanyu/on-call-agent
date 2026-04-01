"""Resumable approval-gated action stub step built on recommendation artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AgentStatus
from memory.checkpoints import (
    ApprovalState,
    ApprovalStatus,
    JsonCheckpointStore,
    PendingVerifier,
    SessionCheckpoint,
)
from permissions.models import PermissionAction, PermissionDecision
from permissions.policy import PermissionPolicy
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
from transcripts.models import (
    CheckpointWrittenEvent,
    ModelStepEvent,
    PermissionDecisionEvent,
    ResumeStartedEvent,
    ToolRequestEvent,
    ToolResultEvent,
    TranscriptEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
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
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    insufficiency_reason: str | None = None


@dataclass(slots=True)
class _ActionStubResumeContext:
    checkpoint_path: Path
    transcript_path: Path
    checkpoint: SessionCheckpoint
    transcript_events: tuple[TranscriptEvent, ...]
    recommendation_output: IncidentRecommendationOutput | None
    recommendation_verifier_passed: bool


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
        step_index = context.checkpoint.current_step + 1
        transcript_store = JsonlTranscriptStore(context.transcript_path)
        checkpoint_store = JsonCheckpointStore(context.checkpoint_path)

        transcript_store.append(
            ResumeStartedEvent(
                session_id=request.session_id,
                step_index=step_index,
                checkpoint_id=context.checkpoint.checkpoint_id,
                reason=request.resume_reason,
            )
        )

        branch, insufficiency_reason = self._select_branch(context)
        recommendation_output = context.recommendation_output
        transcript_store.append(
            ModelStepEvent(
                session_id=request.session_id,
                step_index=step_index,
                summary=self._model_step_summary(branch, context, recommendation_output),
                planned_verifiers=[self.verifier.definition.name],
            )
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        action_stub_output: IncidentActionStubOutput | None = None

        if branch is ActionStubBranch.BUILD_ACTION_STUB:
            permission_decision = self.permission_policy.decide(self.tool.definition)
            transcript_store.append(
                PermissionDecisionEvent(
                    session_id=request.session_id,
                    step_index=step_index,
                    decision=permission_decision,
                )
            )
            if permission_decision.action is not PermissionAction.ALLOW:
                msg = "incident action stub tool must remain read-only and allowed by default"
                raise RuntimeError(msg)

            if recommendation_output is None:
                msg = "action-stub branch requires a durable recommendation record"
                raise RuntimeError(msg)

            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={
                    "recommendation_output": recommendation_output.model_dump(mode="json")
                },
            )
            call_id = f"{request.session_id}-incident-action-stub-tool"
            transcript_store.append(
                ToolRequestEvent(
                    session_id=request.session_id,
                    step_index=step_index,
                    call_id=call_id,
                    tool_call=tool_call,
                )
            )
            tool_result = await self.tool.execute(tool_call)
            transcript_store.append(
                ToolResultEvent(
                    session_id=request.session_id,
                    step_index=step_index,
                    call_id=call_id,
                    tool_name=self.tool.definition.name,
                    result=tool_result,
                )
            )
            action_stub_output = self._parse_action_stub_output(tool_result)

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "recommendation_phase": context.checkpoint.current_phase,
                "recommendation_verifier_passed": context.recommendation_verifier_passed,
                "insufficiency_reason": insufficiency_reason,
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
        verifier_result = await self.verifier.verify(verifier_request)
        transcript_store.append(
            VerifierResultEvent(
                session_id=request.session_id,
                step_index=step_index,
                verifier_name=self.verifier.definition.name,
                request=verifier_request,
                result=verifier_result,
            )
        )

        checkpoint = SessionCheckpoint(
            checkpoint_id=f"{request.session_id}-incident-action-stub",
            session_id=request.session_id,
            incident_id=context.checkpoint.incident_id,
            current_phase=self._current_phase(
                branch=branch,
                verifier_status=verifier_result.status,
                action_stub_output=action_stub_output,
            ),
            current_step=step_index,
            selected_skills=context.checkpoint.selected_skills,
            pending_verifier=self._pending_verifier(verifier_request, verifier_result.status),
            approval_state=self._approval_state(action_stub_output, insufficiency_reason),
            summary_of_progress=self._progress_summary(
                branch=branch,
                action_stub_output=action_stub_output,
                verifier_result=verifier_result,
                insufficiency_reason=insufficiency_reason,
            ),
        )
        checkpoint_store.write(checkpoint)
        transcript_store.append(
            CheckpointWrittenEvent(
                session_id=request.session_id,
                step_index=step_index,
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_path=context.checkpoint_path,
                summary_of_progress=checkpoint.summary_of_progress,
            )
        )

        return IncidentActionStubStepResult(
            session_id=request.session_id,
            incident_id=context.checkpoint.incident_id,
            resumed_successfully=branch is ActionStubBranch.BUILD_ACTION_STUB,
            branch=branch,
            consulted_artifacts=ActionStubResumeArtifacts(
                checkpoint_path=context.checkpoint_path,
                transcript_path=context.transcript_path,
                previous_checkpoint_id=context.checkpoint.checkpoint_id,
                previous_phase=context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.transcript_events),
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
            runner_status=self._runner_status(branch, verifier_result.status, action_stub_output),
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
            checkpoint_path=context.checkpoint_path,
            checkpoint=checkpoint,
            insufficiency_reason=insufficiency_reason,
        )

    def _load_context(self, session_id: str) -> _ActionStubResumeContext:
        checkpoint_path = self.checkpoint_root / f"{session_id}.json"
        transcript_path = self.transcript_root / f"{session_id}.jsonl"
        checkpoint = JsonCheckpointStore(checkpoint_path).load()
        transcript_events = JsonlTranscriptStore(transcript_path).read_all()

        return _ActionStubResumeContext(
            checkpoint_path=checkpoint_path,
            transcript_path=transcript_path,
            checkpoint=checkpoint,
            transcript_events=transcript_events,
            recommendation_output=self._latest_recommendation_output(transcript_events),
            recommendation_verifier_passed=self._latest_recommendation_verifier_status(
                transcript_events
            )
            is VerifierStatus.PASS,
        )

    def _latest_recommendation_output(
        self,
        transcript_events: tuple[TranscriptEvent, ...],
    ) -> IncidentRecommendationOutput | None:
        for event in reversed(transcript_events):
            if (
                isinstance(event, ToolResultEvent)
                and event.tool_name == "incident_recommendation_builder"
                and event.result.output
            ):
                return IncidentRecommendationOutput.model_validate(event.result.output)
        return None

    def _latest_recommendation_verifier_status(
        self,
        transcript_events: tuple[TranscriptEvent, ...],
    ) -> VerifierStatus | None:
        for event in reversed(transcript_events):
            if (
                isinstance(event, VerifierResultEvent)
                and event.verifier_name == "incident_recommendation_outcome"
            ):
                return event.result.status
        return None

    def _select_branch(
        self,
        context: _ActionStubResumeContext,
    ) -> tuple[ActionStubBranch, str | None]:
        if (
            context.checkpoint.current_phase
            in {"recommendation_supported", "recommendation_conservative"}
            and context.recommendation_verifier_passed
            and context.recommendation_output is not None
        ):
            return ActionStubBranch.BUILD_ACTION_STUB, None
        if (
            context.checkpoint.current_phase
            in {"recommendation_supported", "recommendation_conservative"}
            and context.recommendation_verifier_passed
            and context.recommendation_output is None
        ):
            return (
                ActionStubBranch.INSUFFICIENT_STATE,
                "Recommendation artifacts indicate a verified recommendation record "
                "should exist, but the transcript is missing it.",
            )
        return (
            ActionStubBranch.INSUFFICIENT_STATE,
            "Prior artifacts do not yet contain a verified recommendation record for "
            "approval-gated action stub building.",
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
        return (
            f"Resume did not find a usable verified recommendation record in phase "
            f"{context.checkpoint.current_phase}, so the action-stub step will record "
            "an insufficient-state branch."
        )

    def _parse_action_stub_output(
        self,
        tool_result: ToolResult,
    ) -> IncidentActionStubOutput | None:
        if not tool_result.output:
            return None
        return IncidentActionStubOutput.model_validate(tool_result.output)

    def _current_phase(
        self,
        branch: ActionStubBranch,
        verifier_status: VerifierStatus,
        action_stub_output: IncidentActionStubOutput | None,
    ) -> str:
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

    def _pending_verifier(
        self,
        verifier_request: VerifierRequest,
        verifier_status: VerifierStatus,
    ) -> PendingVerifier | None:
        if verifier_status is VerifierStatus.PASS:
            return None
        return PendingVerifier(
            verifier_name=self.verifier.definition.name,
            request=verifier_request,
        )

    def _approval_state(
        self,
        action_stub_output: IncidentActionStubOutput | None,
        insufficiency_reason: str | None,
    ) -> ApprovalState:
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
            )
        return ApprovalState(
            status=ApprovalStatus.NONE,
            reason=action_stub_output.approval_gate.conservative_reason,
        )

    def _progress_summary(
        self,
        branch: ActionStubBranch,
        action_stub_output: IncidentActionStubOutput | None,
        verifier_result: VerifierResult,
        insufficiency_reason: str | None,
    ) -> str:
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
    ) -> AgentStatus:
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        if verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if branch is ActionStubBranch.INSUFFICIENT_STATE:
            return AgentStatus.VERIFYING
        if action_stub_output is not None and action_stub_output.action_candidate_created:
            return AgentStatus.WAITING_FOR_APPROVAL
        return AgentStatus.RUNNING
