"""Resumable post-action outcome verification step for the live deployment-regression slice."""

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
from tools.implementations.deployment_outcome_probe import (
    DeploymentOutcomeProbeOutput,
    DeploymentOutcomeProbeTool,
)
from tools.implementations.deployment_rollback import DeploymentRollbackExecutionOutput
from tools.implementations.incident_hypothesis import (
    DEPLOYMENT_REGRESSION_VALIDATION_GAP,
    IncidentHypothesisOutput,
)
from tools.implementations.incident_recommendation import IncidentRecommendationOutput
from tools.implementations.incident_triage import IncidentTriageInput
from tools.models import ToolCall, ToolResult
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus
from verifiers.implementations.deployment_outcome_probe import (
    DeploymentOutcomeProbeVerifier,
    OutcomeProbeBranch,
)


class OutcomeVerificationResumeArtifacts(BaseModel):
    """Durable artifacts consulted by the outcome verification step."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_path: Path
    transcript_path: Path
    previous_checkpoint_id: str
    previous_phase: str
    prior_transcript_event_count: int


class DeploymentOutcomeVerificationStepRequest(BaseModel):
    """Structured input for the post-action outcome verification step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    resume_reason: str = "Probe live runtime state after the bounded rollback."


class DeploymentOutcomeVerificationStepResult(BaseModel):
    """Structured result returned by the outcome verification step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    incident_id: str
    resumed_successfully: bool
    branch: OutcomeProbeBranch
    consulted_artifacts: OutcomeVerificationResumeArtifacts
    verifier_name: str
    runner_status: AgentStatus
    verifier_result: VerifierResult
    permission_decision: PermissionDecision | None = None
    tool_result: ToolResult | None = None
    action_execution_output: DeploymentRollbackExecutionOutput | None = None
    outcome_probe_output: DeploymentOutcomeProbeOutput | None = None
    artifact_failure: SyntheticFailure | None = None
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    insufficiency_reason: str | None = None


@dataclass(slots=True)
class _OutcomeVerificationContext:
    harness: ResumableSliceHarness
    artifact_context: SessionArtifactContext
    action_execution_output: DeploymentRollbackExecutionOutput | None
    triage_input: IncidentTriageInput | None
    action_execution_failure: SyntheticFailure | None = None
    action_execution_insufficiency_reason: str | None = None


@dataclass(slots=True)
class DeploymentOutcomeVerificationStep:
    """Probe live runtime state after the bounded rollback and verify recovery."""

    transcript_root: Path = Path("sessions/transcripts")
    checkpoint_root: Path = Path("sessions/checkpoints")
    tool: DeploymentOutcomeProbeTool = field(default_factory=DeploymentOutcomeProbeTool)
    verifier: DeploymentOutcomeProbeVerifier = field(default_factory=DeploymentOutcomeProbeVerifier)
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)

    async def run(
        self,
        request: DeploymentOutcomeVerificationStepRequest,
    ) -> DeploymentOutcomeVerificationStepResult:
        context = self._load_context(request.session_id)
        harness = context.harness
        step_index = harness.step_index

        harness.emit_resume_started(reason=request.resume_reason)

        branch, insufficiency_reason = self._select_branch(context)
        harness.emit_model_step(
            summary=self._model_step_summary(branch),
            planned_verifiers=[self.verifier.definition.name],
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        outcome_probe_output: DeploymentOutcomeProbeOutput | None = None

        if branch is OutcomeProbeBranch.PROBE_OUTCOME:
            if context.action_execution_output is None or context.triage_input is None:
                msg = "outcome verification requires action execution output and triage input"
                raise RuntimeError(msg)
            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={
                    "incident_id": context.action_execution_output.incident_id,
                    "service": context.action_execution_output.service,
                    "service_base_url": context.action_execution_output.service_base_url,
                    "expected_previous_version": (
                        context.triage_input.expected_previous_version
                    ),
                },
            )
            tool_outcome = await harness.execute_read_only_tool(
                tool=self.tool,
                permission_policy=self.permission_policy,
                tool_call=tool_call,
                call_id=f"{request.session_id}-deployment-outcome-probe",
                output_model=DeploymentOutcomeProbeOutput,
                permission_denied_message=(
                    "deployment outcome probe must remain read-only and allowed by default"
                ),
            )
            permission_decision = tool_outcome.permission_decision
            tool_result = tool_outcome.tool_result
            outcome_probe_output = tool_outcome.output

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.artifact_context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "insufficiency_reason": insufficiency_reason,
                "prior_artifact_failure": (
                    context.action_execution_failure.model_dump(mode="json")
                    if context.action_execution_failure is not None
                    else None
                ),
                "outcome_probe_output": (
                    outcome_probe_output.model_dump(mode="json")
                    if outcome_probe_output is not None
                    else None
                ),
            },
        )
        verifier_result = await harness.execute_verifier(
            verifier=self.verifier,
            request=verifier_request,
        )
        artifact_failure = combine_artifact_failure(
            prior_failure=context.action_execution_failure,
            tool_result=tool_result,
            verifier_result=verifier_result,
        )

        checkpoint = SessionCheckpoint(
            checkpoint_id=f"{request.session_id}-deployment-outcome-verification",
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            current_phase=self._current_phase(
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
            operator_shell=context.artifact_context.checkpoint.operator_shell,
            summary_of_progress=self._progress_summary(
                outcome_probe_output=outcome_probe_output,
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
            artifact_context=context.artifact_context,
            action_execution_output=context.action_execution_output,
            outcome_probe_output=outcome_probe_output,
        )

        return DeploymentOutcomeVerificationStepResult(
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            resumed_successfully=branch is OutcomeProbeBranch.PROBE_OUTCOME,
            branch=branch,
            consulted_artifacts=OutcomeVerificationResumeArtifacts(
                checkpoint_path=context.artifact_context.checkpoint_path,
                transcript_path=context.artifact_context.transcript_path,
                previous_checkpoint_id=context.artifact_context.checkpoint.checkpoint_id,
                previous_phase=context.artifact_context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.artifact_context.transcript_events),
            ),
            verifier_name=self.verifier.definition.name,
            runner_status=self._runner_status(
                verifier_status=verifier_result.status,
                artifact_failure=artifact_failure,
            ),
            verifier_result=verifier_result,
            permission_decision=permission_decision,
            tool_result=tool_result,
            action_execution_output=context.action_execution_output,
            outcome_probe_output=outcome_probe_output,
            artifact_failure=artifact_failure,
            checkpoint_path=context.artifact_context.checkpoint_path,
            checkpoint=checkpoint,
            insufficiency_reason=insufficiency_reason,
        )

    def _load_context(self, session_id: str) -> _OutcomeVerificationContext:
        harness = ResumableSliceHarness.load(
            session_id=session_id,
            step_name="deployment_outcome_verification",
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
        )
        artifact_context = harness.artifact_context
        execution_resolution = artifact_context.latest_verified_action_execution_output()
        return _OutcomeVerificationContext(
            harness=harness,
            artifact_context=artifact_context,
            action_execution_output=execution_resolution.artifact,
            triage_input=artifact_context.latest_triage_input(),
            action_execution_failure=execution_resolution.failure,
            action_execution_insufficiency_reason=execution_resolution.reason,
        )

    def _select_branch(
        self,
        context: _OutcomeVerificationContext,
    ) -> tuple[OutcomeProbeBranch, str | None]:
        if context.action_execution_output is None:
            return (
                OutcomeProbeBranch.INSUFFICIENT_STATE,
                context.action_execution_insufficiency_reason
                or "Post-action verification requires a verified rollback execution record.",
            )
        if context.triage_input is None or context.triage_input.service_base_url is None:
            return (
                OutcomeProbeBranch.INSUFFICIENT_STATE,
                "Outcome verification requires the original service_base_url from incident intake.",
            )
        return OutcomeProbeBranch.PROBE_OUTCOME, None

    def _model_step_summary(self, branch: OutcomeProbeBranch) -> str:
        if branch is OutcomeProbeBranch.PROBE_OUTCOME:
            return (
                "A verified rollback execution exists, so the runtime will probe live health, "
                "deployment, and metrics endpoints to verify recovery."
            )
        return (
            "Outcome verification cannot run yet because the rollback execution artifact or "
            "live target context is missing."
        )

    def _current_phase(
        self,
        *,
        verifier_status: VerifierStatus,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return "outcome_verification_failed_artifacts"
        if verifier_status is VerifierStatus.PASS:
            return "outcome_verification_succeeded"
        if verifier_status is VerifierStatus.FAIL:
            return "outcome_verification_failed_verification"
        return "outcome_verification_unverified"

    def _progress_summary(
        self,
        *,
        outcome_probe_output: DeploymentOutcomeProbeOutput | None,
        verifier_result: VerifierResult,
        insufficiency_reason: str | None,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return (
                "Outcome verification failed due to artifact failure: "
                f"{artifact_failure.reason}"
            )
        if outcome_probe_output is not None:
            return (
                f"Outcome verification probed version {outcome_probe_output.current_version} "
                f"with health_status={outcome_probe_output.health_status}. "
                f"Verifier status: {verifier_result.status}."
            )
        return (
            "Outcome verification did not run. "
            f"Reason: {insufficiency_reason or 'missing rollback execution artifact'} "
            f"Verifier status: {verifier_result.status}."
        )

    def _runner_status(
        self,
        *,
        verifier_status: VerifierStatus,
        artifact_failure: SyntheticFailure | None,
    ) -> AgentStatus:
        if artifact_failure is not None or verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        return AgentStatus.COMPLETED

    def _working_memory_root(self) -> Path:
        return self.checkpoint_root.parent / "working_memory"

    def _write_incident_working_memory(
        self,
        *,
        session_id: str,
        checkpoint: SessionCheckpoint,
        verifier_result: VerifierResult,
        artifact_context: SessionArtifactContext,
        action_execution_output: DeploymentRollbackExecutionOutput | None,
        outcome_probe_output: DeploymentOutcomeProbeOutput | None,
    ) -> None:
        if (
            verifier_result.status is not VerifierStatus.PASS
            or action_execution_output is None
            or outcome_probe_output is None
        ):
            return

        hypothesis_output = artifact_context.latest_verified_hypothesis_output().artifact
        recommendation_output = artifact_context.latest_verified_recommendation_output().artifact
        if hypothesis_output is None or recommendation_output is None:
            return

        prior_memory = artifact_context.latest_incident_working_memory()
        JsonIncidentWorkingMemoryStore.for_incident(
            checkpoint.incident_id,
            root=self._working_memory_root(),
        ).write(
            IncidentWorkingMemory(
                incident_id=checkpoint.incident_id,
                service=outcome_probe_output.service,
                source_session_id=session_id,
                source_checkpoint_id=checkpoint.checkpoint_id,
                source_phase=checkpoint.current_phase,
                last_updated_by_step="deployment_outcome_verification",
                leading_hypothesis=LeadingHypothesisSnapshot(
                    hypothesis_type=hypothesis_output.hypothesis_type,
                    summary=hypothesis_output.rationale_summary,
                    evidence_supported=hypothesis_output.evidence_supported,
                ),
                unresolved_gaps=self._resolved_unresolved_gaps(
                    prior_memory=prior_memory,
                    hypothesis_output=hypothesis_output,
                ),
                important_evidence_references=self._important_evidence_references(
                    prior_memory=prior_memory,
                    hypothesis_output=hypothesis_output,
                    recommendation_output=recommendation_output,
                    action_execution_output=action_execution_output,
                    outcome_probe_output=outcome_probe_output,
                ),
                recommendation=RecommendationSnapshot(
                    recommendation_type=recommendation_output.recommendation_type,
                    summary=recommendation_output.action_summary,
                    required_approval_level=recommendation_output.required_approval_level,
                    more_investigation_required=False,
                ),
                compact_handoff_note=self._compact_handoff_note(
                    action_execution_output=action_execution_output,
                    outcome_probe_output=outcome_probe_output,
                ),
            )
        )

    def _resolved_unresolved_gaps(
        self,
        *,
        prior_memory: IncidentWorkingMemory | None,
        hypothesis_output: IncidentHypothesisOutput,
    ) -> list[str]:
        unresolved_gaps = (
            prior_memory.unresolved_gaps
            if prior_memory is not None
            else hypothesis_output.unresolved_gaps
        )
        return [
            gap
            for gap in unresolved_gaps
            if gap != DEPLOYMENT_REGRESSION_VALIDATION_GAP
        ]

    def _important_evidence_references(
        self,
        *,
        prior_memory: IncidentWorkingMemory | None,
        hypothesis_output: IncidentHypothesisOutput,
        recommendation_output: IncidentRecommendationOutput,
        action_execution_output: DeploymentRollbackExecutionOutput,
        outcome_probe_output: DeploymentOutcomeProbeOutput,
    ) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    *(
                        prior_memory.important_evidence_references
                        if prior_memory is not None
                        else []
                    ),
                    f"evidence:{hypothesis_output.evidence_snapshot_id}",
                    f"investigation_target:{hypothesis_output.evidence_investigation_target}",
                    *recommendation_output.supporting_artifact_refs,
                    (
                        f"rollback:{action_execution_output.observed_version_before}->"
                        f"{action_execution_output.observed_version_after}"
                    ),
                    action_execution_output.service_base_url,
                    *outcome_probe_output.evidence_refs,
                ]
            )
        )

    def _compact_handoff_note(
        self,
        *,
        action_execution_output: DeploymentRollbackExecutionOutput,
        outcome_probe_output: DeploymentOutcomeProbeOutput,
    ) -> str:
        return (
            f"Rollback executed for {action_execution_output.service} from "
            f"{action_execution_output.observed_version_before} to "
            f"{action_execution_output.observed_version_after}. "
            f"Outcome verification passed with health_status="
            f"{outcome_probe_output.health_status}, error_rate="
            f"{outcome_probe_output.error_rate:.2f}, timeout_rate="
            f"{outcome_probe_output.timeout_rate:.2f}."
        )
