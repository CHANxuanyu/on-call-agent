"""Resumable recommendation step built on hypothesis artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AgentStatus
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import SessionCheckpoint
from memory.incident_working_memory import (
    IncidentWorkingMemory,
    JsonIncidentWorkingMemoryStore,
    LeadingHypothesisSnapshot,
    RecommendationSnapshot,
)
from permissions.models import PermissionDecision
from permissions.policy import PermissionPolicy
from runtime.harness import (
    ResumableSliceHarness,
    combine_artifact_failure,
    pending_verifier_for_status,
)
from runtime.models import SyntheticFailure
from tools.implementations.incident_hypothesis import IncidentHypothesisOutput
from tools.implementations.incident_recommendation import (
    IncidentRecommendationBuilderTool,
    IncidentRecommendationOutput,
    RecommendationApprovalLevel,
    RecommendationType,
    recommendation_requires_approval,
)
from tools.models import ToolCall, ToolResult
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
    artifact_failure: SyntheticFailure | None = None
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    insufficiency_reason: str | None = None


@dataclass(slots=True)
class _RecommendationResumeContext:
    harness: ResumableSliceHarness
    artifact_context: SessionArtifactContext
    hypothesis_output: IncidentHypothesisOutput | None
    hypothesis_verifier_passed: bool
    hypothesis_failure: SyntheticFailure | None = None
    hypothesis_insufficiency_reason: str | None = None


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
        harness = context.harness
        step_index = harness.step_index

        harness.emit_resume_started(reason=request.resume_reason)

        branch, insufficiency_reason = self._select_branch(context)
        hypothesis_output = context.hypothesis_output
        harness.emit_model_step(
            summary=self._model_step_summary(branch, context, hypothesis_output),
            planned_verifiers=[self.verifier.definition.name],
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        recommendation_output: IncidentRecommendationOutput | None = None

        if branch is RecommendationBranch.BUILD_RECOMMENDATION:
            if hypothesis_output is None:
                msg = "recommendation branch requires a durable hypothesis record"
                raise RuntimeError(msg)

            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={"hypothesis_output": hypothesis_output.model_dump(mode="json")},
            )
            tool_outcome = await harness.execute_read_only_tool(
                tool=self.tool,
                permission_policy=self.permission_policy,
                tool_call=tool_call,
                call_id=f"{request.session_id}-incident-recommendation-tool",
                output_model=IncidentRecommendationOutput,
                permission_denied_message=(
                    "incident recommendation tool must remain read-only and allowed by default"
                ),
            )
            permission_decision = tool_outcome.permission_decision
            tool_result = tool_outcome.tool_result
            recommendation_output = tool_outcome.output

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.artifact_context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "hypothesis_phase": context.artifact_context.checkpoint.current_phase,
                "hypothesis_verifier_passed": context.hypothesis_verifier_passed,
                "insufficiency_reason": insufficiency_reason,
                "prior_artifact_failure": (
                    context.hypothesis_failure.model_dump(mode="json")
                    if context.hypothesis_failure is not None
                    else None
                ),
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
        verifier_result = await harness.execute_verifier(
            verifier=self.verifier,
            request=verifier_request,
        )
        artifact_failure = combine_artifact_failure(
            prior_failure=context.hypothesis_failure,
            tool_result=tool_result,
            verifier_result=verifier_result,
        )

        checkpoint = SessionCheckpoint(
            checkpoint_id=f"{request.session_id}-incident-recommendation",
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            current_phase=self._current_phase(
                branch=branch,
                verifier_status=verifier_result.status,
                recommendation_output=recommendation_output,
                artifact_failure=artifact_failure,
            ),
            current_step=step_index,
            selected_skills=context.artifact_context.checkpoint.selected_skills,
            pending_verifier=pending_verifier_for_status(
                verifier_name=self.verifier.definition.name,
                verifier_request=verifier_request,
                verifier_status=verifier_result.status,
            ),
            summary_of_progress=self._progress_summary(
                branch=branch,
                recommendation_output=recommendation_output,
                verifier_result=verifier_result,
                insufficiency_reason=insufficiency_reason,
                artifact_failure=artifact_failure,
            ),
        )
        harness.write_checkpoint(checkpoint)
        self._write_incident_working_memory(
            session_id=request.session_id,
            checkpoint=checkpoint,
            verifier_result=verifier_result,
            hypothesis_output=hypothesis_output,
            recommendation_output=recommendation_output,
        )

        return IncidentRecommendationStepResult(
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            resumed_successfully=branch is RecommendationBranch.BUILD_RECOMMENDATION,
            branch=branch,
            consulted_artifacts=RecommendationResumeArtifacts(
                checkpoint_path=context.artifact_context.checkpoint_path,
                transcript_path=context.artifact_context.transcript_path,
                previous_checkpoint_id=context.artifact_context.checkpoint.checkpoint_id,
                previous_phase=context.artifact_context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.artifact_context.transcript_events),
                hypothesis_verifier_passed=context.hypothesis_verifier_passed,
            ),
            consumed_hypothesis_output=hypothesis_output,
            recommendation_action_name=(
                self.tool.definition.name
                if branch is RecommendationBranch.BUILD_RECOMMENDATION
                else None
            ),
            verifier_name=self.verifier.definition.name,
            runner_status=self._runner_status(
                branch,
                verifier_result.status,
                artifact_failure,
            ),
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
            artifact_failure=artifact_failure,
            checkpoint_path=context.artifact_context.checkpoint_path,
            checkpoint=checkpoint,
            insufficiency_reason=insufficiency_reason,
        )

    def _load_context(self, session_id: str) -> _RecommendationResumeContext:
        harness = ResumableSliceHarness.load(
            session_id=session_id,
            step_name="incident_recommendation",
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            working_memory_root=self._working_memory_root(),
        )
        artifact_context = harness.artifact_context
        hypothesis_resolution = artifact_context.hypothesis_output_for_recommendation_step()
        hypothesis_record = artifact_context.latest_hypothesis_output()
        return _RecommendationResumeContext(
            harness=harness,
            artifact_context=artifact_context,
            hypothesis_output=hypothesis_resolution.artifact,
            hypothesis_verifier_passed=hypothesis_record.verifier_status is VerifierStatus.PASS,
            hypothesis_failure=hypothesis_resolution.failure,
            hypothesis_insufficiency_reason=hypothesis_resolution.reason,
        )

    def _select_branch(
        self,
        context: _RecommendationResumeContext,
    ) -> tuple[RecommendationBranch, str | None]:
        if context.hypothesis_output is not None:
            return RecommendationBranch.BUILD_RECOMMENDATION, None
        return (
            RecommendationBranch.INSUFFICIENT_STATE,
            context.hypothesis_insufficiency_reason
            or "Prior artifacts do not yet contain a verified incident hypothesis.",
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
        if context.hypothesis_failure is not None:
            return (
                "Resume found a structured hypothesis artifact failure in phase "
                f"{context.artifact_context.checkpoint.current_phase}, so the "
                "recommendation step will record a failure-aware insufficient-state branch."
            )
        return (
            "Resume did not find a usable verified hypothesis record in phase "
            f"{context.artifact_context.checkpoint.current_phase}, so the "
            "recommendation step will record "
            "an insufficient-state branch."
        )

    def _current_phase(
        self,
        branch: RecommendationBranch,
        verifier_status: VerifierStatus,
        recommendation_output: IncidentRecommendationOutput | None,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return "recommendation_failed_artifacts"
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

    def _progress_summary(
        self,
        branch: RecommendationBranch,
        recommendation_output: IncidentRecommendationOutput | None,
        verifier_result: VerifierResult,
        insufficiency_reason: str | None,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return (
                f"Recommendation step encountered a structured artifact failure: "
                f"{artifact_failure.reason} Verifier status: {verifier_result.status}."
            )
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
        artifact_failure: SyntheticFailure | None,
    ) -> AgentStatus:
        if artifact_failure is not None:
            return AgentStatus.FAILED
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        if verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if branch is RecommendationBranch.BUILD_RECOMMENDATION:
            return AgentStatus.RUNNING
        return AgentStatus.VERIFYING

    def _working_memory_root(self) -> Path:
        return self.checkpoint_root.parent / "working_memory"

    def _write_incident_working_memory(
        self,
        *,
        session_id: str,
        checkpoint: SessionCheckpoint,
        verifier_result: VerifierResult,
        hypothesis_output: IncidentHypothesisOutput | None,
        recommendation_output: IncidentRecommendationOutput | None,
    ) -> None:
        if (
            verifier_result.status is not VerifierStatus.PASS
            or hypothesis_output is None
            or recommendation_output is None
        ):
            return

        JsonIncidentWorkingMemoryStore.for_incident(
            checkpoint.incident_id,
            root=self._working_memory_root(),
        ).write(
            IncidentWorkingMemory(
                incident_id=checkpoint.incident_id,
                service=recommendation_output.service,
                source_session_id=session_id,
                source_checkpoint_id=checkpoint.checkpoint_id,
                source_phase=checkpoint.current_phase,
                last_updated_by_step="incident_recommendation",
                leading_hypothesis=LeadingHypothesisSnapshot(
                    hypothesis_type=hypothesis_output.hypothesis_type,
                    summary=hypothesis_output.rationale_summary,
                    evidence_supported=hypothesis_output.evidence_supported,
                ),
                unresolved_gaps=hypothesis_output.unresolved_gaps,
                important_evidence_references=self._important_evidence_references(
                    hypothesis_output,
                    recommendation_output,
                ),
                recommendation=RecommendationSnapshot(
                    recommendation_type=recommendation_output.recommendation_type,
                    summary=recommendation_output.action_summary,
                    required_approval_level=recommendation_output.required_approval_level,
                    more_investigation_required=(
                        recommendation_output.more_investigation_required
                    ),
                ),
                compact_handoff_note=self._compact_handoff_note(
                    hypothesis_output,
                    recommendation_output,
                ),
            )
        )

    def _important_evidence_references(
        self,
        hypothesis_output: IncidentHypothesisOutput,
        recommendation_output: IncidentRecommendationOutput,
    ) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    f"evidence:{hypothesis_output.evidence_snapshot_id}",
                    f"investigation_target:{hypothesis_output.evidence_investigation_target}",
                    *recommendation_output.supporting_artifact_refs,
                ]
            )
        )

    def _compact_handoff_note(
        self,
        hypothesis_output: IncidentHypothesisOutput,
        recommendation_output: IncidentRecommendationOutput,
    ) -> str:
        approval_note = (
            "Future non-read-only work remains approval-gated."
            if recommendation_requires_approval(recommendation_output)
            else "No approval-gated action candidate is justified yet."
        )
        return (
            f"Current verified hypothesis for {hypothesis_output.service} is "
            f"{hypothesis_output.hypothesis_type}. "
            f"Current recommendation is {recommendation_output.recommendation_type}. "
            "This step validates rollback readiness before any action candidate is proposed. "
            f"{approval_note}"
        )
