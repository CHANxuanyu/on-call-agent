"""Resumable recommendation step built on hypothesis artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AgentStatus
from memory.checkpoints import JsonCheckpointStore, PendingVerifier, SessionCheckpoint
from permissions.models import PermissionAction, PermissionDecision
from permissions.policy import PermissionPolicy
from tools.implementations.incident_hypothesis import IncidentHypothesisOutput
from tools.implementations.incident_recommendation import (
    IncidentRecommendationBuilderTool,
    IncidentRecommendationOutput,
    RecommendationApprovalLevel,
    RecommendationType,
    recommendation_requires_approval,
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
from verifiers.implementations.incident_recommendation import (
    IncidentRecommendationOutcomeVerifier,
    RecommendationBranch,
)


class RecommendationResumeArtifacts(BaseModel):
    """Durable artifacts consulted by the recommendation step."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_path: Path
    transcript_path: Path
    previous_checkpoint_id: str
    previous_phase: str
    prior_transcript_event_count: int
    hypothesis_verifier_passed: bool


class IncidentRecommendationStepRequest(BaseModel):
    """Structured input for the recommendation continuation step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    resume_reason: str = "Continue from the latest incident-hypothesis artifacts."


class IncidentRecommendationStepResult(BaseModel):
    """Structured result returned by the recommendation step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    incident_id: str
    resumed_successfully: bool
    branch: RecommendationBranch
    consulted_artifacts: RecommendationResumeArtifacts
    consumed_hypothesis_output: IncidentHypothesisOutput | None = None
    recommendation_action_name: str | None = None
    verifier_name: str
    runner_status: AgentStatus
    hypothesis_supported: bool | None = None
    conservative_due_to_insufficient_evidence: bool | None = None
    more_follow_up_required: bool
    future_action_requires_approval: bool | None = None
    verifier_result: VerifierResult
    permission_decision: PermissionDecision | None = None
    tool_result: ToolResult | None = None
    recommendation_output: IncidentRecommendationOutput | None = None
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    insufficiency_reason: str | None = None


@dataclass(slots=True)
class _RecommendationResumeContext:
    checkpoint_path: Path
    transcript_path: Path
    checkpoint: SessionCheckpoint
    transcript_events: tuple[TranscriptEvent, ...]
    hypothesis_output: IncidentHypothesisOutput | None
    hypothesis_verifier_passed: bool


@dataclass(slots=True)
class IncidentRecommendationStep:
    """Consumes one hypothesis record and builds one verifier-gated recommendation."""

    transcript_root: Path = Path("sessions/transcripts")
    checkpoint_root: Path = Path("sessions/checkpoints")
    tool: IncidentRecommendationBuilderTool = field(
        default_factory=IncidentRecommendationBuilderTool
    )
    verifier: IncidentRecommendationOutcomeVerifier = field(
        default_factory=IncidentRecommendationOutcomeVerifier
    )
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)

    async def run(
        self,
        request: IncidentRecommendationStepRequest,
    ) -> IncidentRecommendationStepResult:
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
        hypothesis_output = context.hypothesis_output
        transcript_store.append(
            ModelStepEvent(
                session_id=request.session_id,
                step_index=step_index,
                summary=self._model_step_summary(branch, context, hypothesis_output),
                planned_verifiers=[self.verifier.definition.name],
            )
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        recommendation_output: IncidentRecommendationOutput | None = None

        if branch is RecommendationBranch.BUILD_RECOMMENDATION:
            permission_decision = self.permission_policy.decide(self.tool.definition)
            transcript_store.append(
                PermissionDecisionEvent(
                    session_id=request.session_id,
                    step_index=step_index,
                    decision=permission_decision,
                )
            )
            if permission_decision.action is not PermissionAction.ALLOW:
                msg = "incident recommendation tool must remain read-only and allowed by default"
                raise RuntimeError(msg)

            if hypothesis_output is None:
                msg = "recommendation branch requires a durable hypothesis record"
                raise RuntimeError(msg)

            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={"hypothesis_output": hypothesis_output.model_dump(mode="json")},
            )
            call_id = f"{request.session_id}-incident-recommendation-tool"
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
            recommendation_output = self._parse_recommendation_output(tool_result)

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "hypothesis_phase": context.checkpoint.current_phase,
                "hypothesis_verifier_passed": context.hypothesis_verifier_passed,
                "insufficiency_reason": insufficiency_reason,
                "hypothesis_output": (
                    hypothesis_output.model_dump(mode="json")
                    if hypothesis_output is not None
                    else None
                ),
                "recommendation_output": (
                    recommendation_output.model_dump(mode="json")
                    if recommendation_output is not None
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
            checkpoint_id=f"{request.session_id}-incident-recommendation",
            session_id=request.session_id,
            incident_id=context.checkpoint.incident_id,
            current_phase=self._current_phase(
                branch=branch,
                verifier_status=verifier_result.status,
                recommendation_output=recommendation_output,
            ),
            current_step=step_index,
            selected_skills=context.checkpoint.selected_skills,
            pending_verifier=self._pending_verifier(verifier_request, verifier_result.status),
            summary_of_progress=self._progress_summary(
                branch=branch,
                recommendation_output=recommendation_output,
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

        return IncidentRecommendationStepResult(
            session_id=request.session_id,
            incident_id=context.checkpoint.incident_id,
            resumed_successfully=branch is RecommendationBranch.BUILD_RECOMMENDATION,
            branch=branch,
            consulted_artifacts=RecommendationResumeArtifacts(
                checkpoint_path=context.checkpoint_path,
                transcript_path=context.transcript_path,
                previous_checkpoint_id=context.checkpoint.checkpoint_id,
                previous_phase=context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.transcript_events),
                hypothesis_verifier_passed=context.hypothesis_verifier_passed,
            ),
            consumed_hypothesis_output=hypothesis_output,
            recommendation_action_name=(
                self.tool.definition.name
                if branch is RecommendationBranch.BUILD_RECOMMENDATION
                else None
            ),
            verifier_name=self.verifier.definition.name,
            runner_status=self._runner_status(branch, verifier_result.status),
            hypothesis_supported=(
                hypothesis_output.evidence_supported if hypothesis_output is not None else None
            ),
            conservative_due_to_insufficient_evidence=(
                recommendation_output.recommendation_type
                is RecommendationType.INVESTIGATE_MORE
                if recommendation_output is not None
                else None
            ),
            more_follow_up_required=True,
            future_action_requires_approval=(
                recommendation_requires_approval(recommendation_output)
                if recommendation_output is not None
                else None
            ),
            verifier_result=verifier_result,
            permission_decision=permission_decision,
            tool_result=tool_result,
            recommendation_output=recommendation_output,
            checkpoint_path=context.checkpoint_path,
            checkpoint=checkpoint,
            insufficiency_reason=insufficiency_reason,
        )

    def _load_context(self, session_id: str) -> _RecommendationResumeContext:
        checkpoint_path = self.checkpoint_root / f"{session_id}.json"
        transcript_path = self.transcript_root / f"{session_id}.jsonl"
        checkpoint = JsonCheckpointStore(checkpoint_path).load()
        transcript_events = JsonlTranscriptStore(transcript_path).read_all()

        return _RecommendationResumeContext(
            checkpoint_path=checkpoint_path,
            transcript_path=transcript_path,
            checkpoint=checkpoint,
            transcript_events=transcript_events,
            hypothesis_output=self._latest_hypothesis_output(transcript_events),
            hypothesis_verifier_passed=self._latest_hypothesis_verifier_status(
                transcript_events
            )
            is VerifierStatus.PASS,
        )

    def _latest_hypothesis_output(
        self,
        transcript_events: tuple[TranscriptEvent, ...],
    ) -> IncidentHypothesisOutput | None:
        for event in reversed(transcript_events):
            if (
                isinstance(event, ToolResultEvent)
                and event.tool_name == "incident_hypothesis_builder"
                and event.result.output
            ):
                return IncidentHypothesisOutput.model_validate(event.result.output)
        return None

    def _latest_hypothesis_verifier_status(
        self,
        transcript_events: tuple[TranscriptEvent, ...],
    ) -> VerifierStatus | None:
        for event in reversed(transcript_events):
            if (
                isinstance(event, VerifierResultEvent)
                and event.verifier_name == "incident_hypothesis_outcome"
            ):
                return event.result.status
        return None

    def _select_branch(
        self,
        context: _RecommendationResumeContext,
    ) -> tuple[RecommendationBranch, str | None]:
        if (
            context.checkpoint.current_phase
            in {"hypothesis_supported", "hypothesis_insufficient_evidence"}
            and context.hypothesis_verifier_passed
            and context.hypothesis_output is not None
        ):
            return RecommendationBranch.BUILD_RECOMMENDATION, None
        if (
            context.checkpoint.current_phase
            in {"hypothesis_supported", "hypothesis_insufficient_evidence"}
            and context.hypothesis_verifier_passed
            and context.hypothesis_output is None
        ):
            return (
                RecommendationBranch.INSUFFICIENT_STATE,
                "Hypothesis artifacts indicate a verified hypothesis record should exist, "
                "but the transcript is missing it.",
            )
        return (
            RecommendationBranch.INSUFFICIENT_STATE,
            "Prior artifacts do not yet contain a verified hypothesis record for "
            "recommendation building.",
        )

    def _model_step_summary(
        self,
        branch: RecommendationBranch,
        context: _RecommendationResumeContext,
        hypothesis_output: IncidentHypothesisOutput | None,
    ) -> str:
        if branch is RecommendationBranch.BUILD_RECOMMENDATION and hypothesis_output is not None:
            return (
                f"Resume recovered hypothesis {hypothesis_output.hypothesis_type} from "
                "durable artifacts and will build one deterministic recommendation."
            )
        return (
            f"Resume did not find a usable verified hypothesis record in phase "
            f"{context.checkpoint.current_phase}, so the recommendation step will record "
            "an insufficient-state branch."
        )

    def _parse_recommendation_output(
        self,
        tool_result: ToolResult,
    ) -> IncidentRecommendationOutput | None:
        if not tool_result.output:
            return None
        return IncidentRecommendationOutput.model_validate(tool_result.output)

    def _current_phase(
        self,
        branch: RecommendationBranch,
        verifier_status: VerifierStatus,
        recommendation_output: IncidentRecommendationOutput | None,
    ) -> str:
        if verifier_status is VerifierStatus.UNVERIFIED:
            return "recommendation_unverified"
        if verifier_status is VerifierStatus.FAIL:
            return "recommendation_failed_verification"
        if branch is RecommendationBranch.INSUFFICIENT_STATE:
            return "recommendation_deferred"
        if recommendation_output is None:
            return "recommendation_unverified"
        if (
            recommendation_output.required_approval_level
            is RecommendationApprovalLevel.NONE
        ):
            return "recommendation_conservative"
        return "recommendation_supported"

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

    def _progress_summary(
        self,
        branch: RecommendationBranch,
        recommendation_output: IncidentRecommendationOutput | None,
        verifier_result: VerifierResult,
        insufficiency_reason: str | None,
    ) -> str:
        if branch is RecommendationBranch.INSUFFICIENT_STATE:
            return (
                f"Recommendation step deferred. Reason: {insufficiency_reason} "
                f"Verifier status: {verifier_result.status}."
            )
        if recommendation_output is None:
            return (
                "Recommendation step did not produce a structured recommendation. "
                f"Verifier status: {verifier_result.status}."
            )
        return (
            f"Recommendation step produced {recommendation_output.recommendation_type} for "
            f"{recommendation_output.service}. Verifier status: {verifier_result.status}."
        )

    def _runner_status(
        self,
        branch: RecommendationBranch,
        verifier_status: VerifierStatus,
    ) -> AgentStatus:
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        if verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if branch is RecommendationBranch.BUILD_RECOMMENDATION:
            return AgentStatus.RUNNING
        return AgentStatus.VERIFYING
