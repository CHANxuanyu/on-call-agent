"""Resumable evidence-reading step built on follow-up artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AgentStatus
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import SessionCheckpoint
from permissions.models import PermissionDecision
from permissions.policy import PermissionPolicy
from runtime.harness import (
    ResumableSliceHarness,
    combine_artifact_failure,
    pending_verifier_for_status,
)
from runtime.models import SyntheticFailure
from runtime.phases import EVIDENCE_STEP_ENTRY_PHASES, IncidentPhase
from tools.implementations.evidence_reading import EvidenceBundleReaderTool, EvidenceReadOutput
from tools.implementations.follow_up_investigation import (
    FollowUpInvestigationOutput,
    InvestigationTarget,
)
from tools.implementations.incident_triage import IncidentTriageInput
from tools.models import ToolCall, ToolResult
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus
from verifiers.implementations.evidence_reading import (
    EvidenceReadBranch,
    EvidenceReadOutcomeVerifier,
)


class EvidenceResumeArtifacts(BaseModel):
    """Durable artifacts consulted by the evidence-reading step."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_path: Path
    transcript_path: Path
    previous_checkpoint_id: str
    previous_phase: str
    prior_transcript_event_count: int
    follow_up_verifier_passed: bool


class IncidentEvidenceStepRequest(BaseModel):
    """Structured input for the evidence-reading continuation step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    resume_reason: str = "Continue from the latest follow-up investigation artifacts."


class IncidentEvidenceStepResult(BaseModel):
    """Structured result returned by the evidence-reading step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    incident_id: str
    resumed_successfully: bool
    branch: EvidenceReadBranch
    consulted_artifacts: EvidenceResumeArtifacts
    selected_investigation_target: InvestigationTarget | None = None
    evidence_action_name: str | None = None
    verifier_name: str
    runner_status: AgentStatus
    more_follow_up_required: bool
    verifier_result: VerifierResult
    permission_decision: PermissionDecision | None = None
    tool_result: ToolResult | None = None
    evidence_output: EvidenceReadOutput | None = None
    artifact_failure: SyntheticFailure | None = None
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    insufficiency_reason: str | None = None


@dataclass(slots=True)
class _EvidenceResumeContext:
    harness: ResumableSliceHarness
    artifact_context: SessionArtifactContext
    follow_up_output: FollowUpInvestigationOutput | None
    triage_input: IncidentTriageInput | None
    follow_up_verifier_passed: bool
    follow_up_failure: SyntheticFailure | None = None
    follow_up_insufficiency_reason: str | None = None


@dataclass(slots=True)
class IncidentEvidenceStep:
    """Consumes a durable follow-up target and reads one deterministic evidence snapshot."""

    transcript_root: Path = Path("sessions/transcripts")
    checkpoint_root: Path = Path("sessions/checkpoints")
    tool: EvidenceBundleReaderTool = field(default_factory=EvidenceBundleReaderTool)
    verifier: EvidenceReadOutcomeVerifier = field(default_factory=EvidenceReadOutcomeVerifier)
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)

    async def run(self, request: IncidentEvidenceStepRequest) -> IncidentEvidenceStepResult:
        context = self._load_context(request.session_id)
        harness = context.harness
        step_index = harness.step_index

        harness.emit_resume_started(reason=request.resume_reason)

        branch, insufficiency_reason = self._select_branch(context)
        selected_target = (
            context.follow_up_output.investigation_target
            if context.follow_up_output is not None
            else None
        )
        harness.emit_model_step(
            summary=self._model_step_summary(branch, context, selected_target),
            planned_verifiers=[self.verifier.definition.name],
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        evidence_output: EvidenceReadOutput | None = None

        if branch is EvidenceReadBranch.READ_EVIDENCE:
            if context.follow_up_output is None:
                msg = "evidence-reading branch requires a durable follow-up target"
                raise RuntimeError(msg)

            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={
                    "investigation_output": context.follow_up_output.model_dump(mode="json"),
                    "triage_input": (
                        context.triage_input.model_dump(mode="json")
                        if context.triage_input is not None
                        else None
                    ),
                },
            )
            tool_outcome = await harness.execute_read_only_tool(
                tool=self.tool,
                permission_policy=self.permission_policy,
                tool_call=tool_call,
                call_id=f"{request.session_id}-evidence-reader-tool",
                output_model=EvidenceReadOutput,
                permission_denied_message=(
                    "evidence-reading tool must remain read-only and allowed by default"
                ),
            )
            permission_decision = tool_outcome.permission_decision
            tool_result = tool_outcome.tool_result
            evidence_output = tool_outcome.output

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.artifact_context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "follow_up_phase": context.artifact_context.checkpoint.current_phase,
                "follow_up_verifier_passed": context.follow_up_verifier_passed,
                "selected_target": selected_target,
                "insufficiency_reason": insufficiency_reason,
                "prior_artifact_failure": (
                    context.follow_up_failure.model_dump(mode="json")
                    if context.follow_up_failure is not None
                    else None
                ),
                "evidence_output": (
                    evidence_output.model_dump(mode="json")
                    if evidence_output is not None
                    else None
                ),
            },
        )
        verifier_result = await harness.execute_verifier(
            verifier=self.verifier,
            request=verifier_request,
        )
        artifact_failure = combine_artifact_failure(
            prior_failure=context.follow_up_failure,
            tool_result=tool_result,
            verifier_result=verifier_result,
        )

        checkpoint = SessionCheckpoint(
            checkpoint_id=f"{request.session_id}-evidence-read",
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            current_phase=self._current_phase(
                branch=branch,
                previous_phase=context.artifact_context.checkpoint.current_phase,
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
            operator_shell=context.artifact_context.checkpoint.operator_shell,
            summary_of_progress=self._progress_summary(
                branch=branch,
                selected_target=selected_target,
                evidence_output=evidence_output,
                verifier_result=verifier_result,
                insufficiency_reason=insufficiency_reason,
                artifact_failure=artifact_failure,
            ),
        )
        harness.write_checkpoint(checkpoint)

        return IncidentEvidenceStepResult(
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            resumed_successfully=branch is EvidenceReadBranch.READ_EVIDENCE,
            branch=branch,
            consulted_artifacts=EvidenceResumeArtifacts(
                checkpoint_path=context.artifact_context.checkpoint_path,
                transcript_path=context.artifact_context.transcript_path,
                previous_checkpoint_id=context.artifact_context.checkpoint.checkpoint_id,
                previous_phase=context.artifact_context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.artifact_context.transcript_events),
                follow_up_verifier_passed=context.follow_up_verifier_passed,
            ),
            selected_investigation_target=selected_target,
            evidence_action_name=(
                self.tool.definition.name if branch is EvidenceReadBranch.READ_EVIDENCE else None
            ),
            verifier_name=self.verifier.definition.name,
            runner_status=self._runner_status(
                branch=branch,
                previous_phase=context.artifact_context.checkpoint.current_phase,
                verifier_status=verifier_result.status,
                artifact_failure=artifact_failure,
            ),
            more_follow_up_required=self._more_follow_up_required(
                branch=branch,
                previous_phase=context.artifact_context.checkpoint.current_phase,
                verifier_status=verifier_result.status,
            ),
            verifier_result=verifier_result,
            permission_decision=permission_decision,
            tool_result=tool_result,
            evidence_output=evidence_output,
            artifact_failure=artifact_failure,
            checkpoint_path=context.artifact_context.checkpoint_path,
            checkpoint=checkpoint,
            insufficiency_reason=insufficiency_reason,
        )

    def _load_context(self, session_id: str) -> _EvidenceResumeContext:
        harness = ResumableSliceHarness.load(
            session_id=session_id,
            step_name="incident_evidence",
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
        )
        artifact_context = harness.artifact_context
        artifact_context.require_current_phase_in(
            allowed_phases=EVIDENCE_STEP_ENTRY_PHASES,
            boundary_name="incident_evidence step entry",
        )
        follow_up_resolution = artifact_context.follow_up_output_for_evidence_step()
        follow_up_record = artifact_context.latest_follow_up_output()
        return _EvidenceResumeContext(
            harness=harness,
            artifact_context=artifact_context,
            follow_up_output=follow_up_resolution.artifact,
            triage_input=artifact_context.latest_triage_input(),
            follow_up_verifier_passed=follow_up_record.verifier_status is VerifierStatus.PASS,
            follow_up_failure=follow_up_resolution.failure,
            follow_up_insufficiency_reason=follow_up_resolution.reason,
        )

    def _select_branch(
        self,
        context: _EvidenceResumeContext,
    ) -> tuple[EvidenceReadBranch, str | None]:
        if context.follow_up_output is not None:
            return EvidenceReadBranch.READ_EVIDENCE, None
        return (
            EvidenceReadBranch.INSUFFICIENT_STATE,
            context.follow_up_insufficiency_reason
            or "Prior artifacts do not yet contain a verified follow-up investigation target.",
        )

    def _model_step_summary(
        self,
        branch: EvidenceReadBranch,
        context: _EvidenceResumeContext,
        selected_target: InvestigationTarget | None,
    ) -> str:
        if branch is EvidenceReadBranch.READ_EVIDENCE:
            evidence_source = (
                "live runtime endpoints"
                if (
                    context.triage_input is not None
                    and context.triage_input.service_base_url is not None
                    and selected_target is InvestigationTarget.RECENT_DEPLOYMENT
                )
                else "deterministic local fixtures"
            )
            return (
                f"Resume recovered selected target {selected_target} from follow-up artifacts and "
                f"will read one {evidence_source} evidence bundle."
            )
        if context.follow_up_failure is not None:
            return (
                "Resume found a structured follow-up artifact failure in phase "
                f"{context.artifact_context.checkpoint.current_phase}, so the evidence-reading "
                "step will record a failure-aware insufficient-state branch."
            )
        return (
            "Resume did not find a usable selected investigation target in phase "
            f"{context.artifact_context.checkpoint.current_phase}, so the "
            "evidence-reading step will record "
            "an insufficient-state branch."
        )

    def _current_phase(
        self,
        branch: EvidenceReadBranch,
        previous_phase: str,
        verifier_status: VerifierStatus,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return "evidence_reading_failed_artifacts"
        if verifier_status is VerifierStatus.UNVERIFIED:
            return "evidence_reading_unverified"
        if verifier_status is VerifierStatus.FAIL:
            return "evidence_reading_failed_verification"
        if branch is EvidenceReadBranch.READ_EVIDENCE:
            return "evidence_reading_completed"
        if previous_phase == IncidentPhase.FOLLOW_UP_COMPLETE_NO_ACTION:
            return "evidence_reading_not_applicable"
        return "evidence_reading_deferred"

    def _progress_summary(
        self,
        branch: EvidenceReadBranch,
        selected_target: InvestigationTarget | None,
        evidence_output: EvidenceReadOutput | None,
        verifier_result: VerifierResult,
        insufficiency_reason: str | None,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return (
                f"Evidence-reading step encountered a structured artifact failure: "
                f"{artifact_failure.reason} Verifier status: {verifier_result.status}."
            )
        if branch is EvidenceReadBranch.INSUFFICIENT_STATE:
            return (
                f"Evidence-reading step deferred. Reason: {insufficiency_reason} "
                f"Verifier status: {verifier_result.status}."
            )
        if evidence_output is None:
            return (
                f"Evidence-reading step did not produce structured evidence for "
                f"{selected_target}. Verifier status: {verifier_result.status}."
            )
        return (
            f"Evidence-reading step captured snapshot {evidence_output.snapshot_id} for "
            f"{selected_target}. Verifier status: {verifier_result.status}."
        )

    def _runner_status(
        self,
        branch: EvidenceReadBranch,
        previous_phase: str,
        verifier_status: VerifierStatus,
        artifact_failure: SyntheticFailure | None,
    ) -> AgentStatus:
        if artifact_failure is not None:
            return AgentStatus.FAILED
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        if verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if branch is EvidenceReadBranch.READ_EVIDENCE:
            return AgentStatus.RUNNING
        if previous_phase == IncidentPhase.FOLLOW_UP_COMPLETE_NO_ACTION:
            return AgentStatus.COMPLETED
        return AgentStatus.VERIFYING

    def _more_follow_up_required(
        self,
        branch: EvidenceReadBranch,
        previous_phase: str,
        verifier_status: VerifierStatus,
    ) -> bool:
        if verifier_status is not VerifierStatus.PASS:
            return True
        if branch is EvidenceReadBranch.READ_EVIDENCE:
            return True
        return previous_phase != IncidentPhase.FOLLOW_UP_COMPLETE_NO_ACTION
