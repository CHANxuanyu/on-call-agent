"""Resumable follow-up step built on prior triage artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent.state import AgentStatus
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import JsonCheckpointStore, PendingVerifier, SessionCheckpoint
from permissions.models import PermissionAction, PermissionDecision
from permissions.policy import PermissionPolicy
from runtime.phases import FOLLOW_UP_STEP_ENTRY_PHASES, IncidentPhase
from tools.implementations.follow_up_investigation import (
    FollowUpInvestigationOutput,
    InvestigationFocusSelectorTool,
)
from tools.implementations.incident_triage import IncidentTriageOutput
from tools.models import ToolCall, ToolResult
from transcripts.models import (
    CheckpointWrittenEvent,
    ModelStepEvent,
    PermissionDecisionEvent,
    ResumeStartedEvent,
    ToolRequestEvent,
    ToolResultEvent,
    VerifierRequestEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus
from verifiers.implementations.follow_up_investigation import (
    FollowUpBranch,
    FollowUpOutcomeVerifier,
)


class IncidentFollowUpStepRequest(BaseModel):
    """Structured input for the resumable follow-up step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    resume_reason: str = "Continue from the latest checkpointed incident state."


class ResumeArtifacts(BaseModel):
    """Prior durable artifacts consulted by the follow-up step."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_path: Path
    transcript_path: Path
    previous_checkpoint_id: str
    previous_phase: str
    prior_transcript_event_count: int


class IncidentFollowUpStepResult(BaseModel):
    """Structured result returned by the resumable follow-up step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    incident_id: str
    resumed_successfully: bool
    branch: FollowUpBranch
    consulted_artifacts: ResumeArtifacts
    runner_status: AgentStatus
    more_follow_up_required: bool
    triage_was_verified_complete: bool
    verifier_name: str
    verifier_result: VerifierResult
    permission_decision: PermissionDecision | None = None
    tool_result: ToolResult | None = None
    investigation_output: FollowUpInvestigationOutput | None = None
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    no_op_reason: str | None = None


@dataclass(slots=True)
class _ResumeContext:
    artifact_context: SessionArtifactContext
    triage_output: IncidentTriageOutput | None
    triage_was_verified_complete: bool
    triage_insufficiency_reason: str | None = None


@dataclass(slots=True)
class IncidentFollowUpStep:
    """Resumes from triage artifacts and either no-ops or investigates one target."""

    transcript_root: Path = Path("sessions/transcripts")
    checkpoint_root: Path = Path("sessions/checkpoints")
    tool: InvestigationFocusSelectorTool = field(default_factory=InvestigationFocusSelectorTool)
    verifier: FollowUpOutcomeVerifier = field(default_factory=FollowUpOutcomeVerifier)
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)

    async def run(self, request: IncidentFollowUpStepRequest) -> IncidentFollowUpStepResult:
        context = self._load_context(request.session_id)
        step_index = context.artifact_context.checkpoint.current_step + 1
        transcript_store = JsonlTranscriptStore(context.artifact_context.transcript_path)
        checkpoint_store = JsonCheckpointStore(context.artifact_context.checkpoint_path)

        transcript_store.append(
            ResumeStartedEvent(
                session_id=request.session_id,
                step_index=step_index,
                checkpoint_id=context.artifact_context.checkpoint.checkpoint_id,
                reason=request.resume_reason,
            )
        )

        triage_output = context.triage_output
        if triage_output is None:
            msg = (
                context.triage_insufficiency_reason
                or "resume requires prior structured triage output in the transcript"
            )
            raise RuntimeError(msg)

        branch = self._select_branch(
            triage_was_verified_complete=context.triage_was_verified_complete,
            triage_output=triage_output,
        )
        transcript_store.append(
            ModelStepEvent(
                session_id=request.session_id,
                step_index=step_index,
                summary=self._model_step_summary(branch, triage_output),
                planned_verifiers=[self.verifier.definition.name],
            )
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        investigation_output: FollowUpInvestigationOutput | None = None

        if branch is FollowUpBranch.INVESTIGATE:
            permission_decision = self.permission_policy.decide(
                self.tool.definition,
                notes=[
                    "Step 'incident_follow_up' evaluated this tool directly in the "
                    "follow-up slice."
                ],
            )
            transcript_store.append(
                PermissionDecisionEvent(
                    session_id=request.session_id,
                    step_index=step_index,
                    decision=permission_decision,
                )
            )
            if permission_decision.action is not PermissionAction.ALLOW:
                msg = "follow-up investigation tool must remain read-only and allowed by default"
                raise RuntimeError(msg)

            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={"triage_output": triage_output.model_dump(mode="json")},
            )
            call_id = f"{request.session_id}-follow-up-investigation-tool"
            transcript_store.append(
                ToolRequestEvent(
                    session_id=request.session_id,
                    step_index=step_index,
                    call_id=call_id,
                    tool_call=tool_call,
                    risk_level=self.tool.definition.risk_level,
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
            investigation_output = self._parse_investigation_output(tool_result)

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.artifact_context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "triage_verifier_passed": context.triage_was_verified_complete,
                "triage_output": triage_output.model_dump(mode="json"),
                "investigation_output": (
                    investigation_output.model_dump(mode="json")
                    if investigation_output is not None
                    else None
                ),
            },
        )
        transcript_store.append(
            VerifierRequestEvent(
                session_id=request.session_id,
                step_index=step_index,
                verifier_name=self.verifier.definition.name,
                request=verifier_request,
            )
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
            checkpoint_id=f"{request.session_id}-follow-up",
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            current_phase=self._current_phase(branch, verifier_result.status),
            current_step=step_index,
            selected_skills=context.artifact_context.checkpoint.selected_skills,
            pending_verifier=self._pending_verifier(verifier_request, verifier_result.status),
            operator_shell=context.artifact_context.checkpoint.operator_shell,
            summary_of_progress=self._progress_summary(
                branch=branch,
                triage_output=triage_output,
                investigation_output=investigation_output,
                verifier_result=verifier_result,
            ),
        )
        checkpoint_store.write(checkpoint)
        transcript_store.append(
            CheckpointWrittenEvent(
                session_id=request.session_id,
                step_index=step_index,
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_path=context.artifact_context.checkpoint_path,
                summary_of_progress=checkpoint.summary_of_progress,
            )
        )

        return IncidentFollowUpStepResult(
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            resumed_successfully=True,
            branch=branch,
            consulted_artifacts=ResumeArtifacts(
                checkpoint_path=context.artifact_context.checkpoint_path,
                transcript_path=context.artifact_context.transcript_path,
                previous_checkpoint_id=context.artifact_context.checkpoint.checkpoint_id,
                previous_phase=context.artifact_context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.artifact_context.transcript_events),
            ),
            runner_status=self._runner_status(branch, verifier_result.status),
            more_follow_up_required=self._more_follow_up_required(branch, verifier_result.status),
            triage_was_verified_complete=context.triage_was_verified_complete,
            verifier_name=self.verifier.definition.name,
            verifier_result=verifier_result,
            permission_decision=permission_decision,
            tool_result=tool_result,
            investigation_output=investigation_output,
            checkpoint_path=context.artifact_context.checkpoint_path,
            checkpoint=checkpoint,
            no_op_reason=self._no_op_reason(
                branch,
                context.triage_was_verified_complete,
                triage_output,
            ),
        )

    def _load_context(self, session_id: str) -> _ResumeContext:
        artifact_context = SessionArtifactContext.load(
            session_id,
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
        )
        artifact_context.require_current_phase_in(
            allowed_phases=FOLLOW_UP_STEP_ENTRY_PHASES,
            boundary_name="incident_follow_up step entry",
        )
        triage_resolution = artifact_context.required_triage_output()
        return _ResumeContext(
            artifact_context=artifact_context,
            triage_output=triage_resolution.artifact,
            triage_was_verified_complete=(
                artifact_context.phase_is(IncidentPhase.TRIAGE_COMPLETED)
                and artifact_context.has_verified_triage_output()
            ),
            triage_insufficiency_reason=triage_resolution.reason,
        )

    def _select_branch(
        self,
        triage_was_verified_complete: bool,
        triage_output: IncidentTriageOutput,
    ) -> FollowUpBranch:
        if triage_was_verified_complete and not triage_output.unknowns:
            return FollowUpBranch.NO_OP
        return FollowUpBranch.INVESTIGATE

    def _model_step_summary(
        self,
        branch: FollowUpBranch,
        triage_output: IncidentTriageOutput,
    ) -> str:
        if branch is FollowUpBranch.NO_OP:
            return (
                f"Resume confirmed verified triage for {triage_output.incident_id} with no "
                "unresolved unknowns, so the follow-up step will safely no-op."
            )
        return (
            f"Resume found unresolved follow-up work for {triage_output.incident_id}, so the "
            "step will select one read-only investigation target."
        )

    def _parse_investigation_output(
        self,
        tool_result: ToolResult,
    ) -> FollowUpInvestigationOutput | None:
        if not tool_result.output:
            return None
        return FollowUpInvestigationOutput.model_validate(tool_result.output)

    def _current_phase(
        self,
        branch: FollowUpBranch,
        verifier_status: VerifierStatus,
    ) -> str:
        if verifier_status is VerifierStatus.UNVERIFIED:
            return "follow_up_unverified"
        if verifier_status is VerifierStatus.FAIL:
            return "follow_up_failed_verification"
        if branch is FollowUpBranch.NO_OP:
            return "follow_up_complete_no_action"
        return "follow_up_investigation_selected"

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
        branch: FollowUpBranch,
        triage_output: IncidentTriageOutput,
        investigation_output: FollowUpInvestigationOutput | None,
        verifier_result: VerifierResult,
    ) -> str:
        if branch is FollowUpBranch.NO_OP:
            return (
                f"Resume confirmed no additional follow-up action is needed for "
                f"{triage_output.incident_id}. Verifier status: {verifier_result.status}."
            )
        if investigation_output is None:
            return (
                f"Resume attempted follow-up investigation for {triage_output.incident_id} but "
                f"did not produce structured output. Verifier status: {verifier_result.status}."
            )
        return (
            f"Resume selected follow-up target {investigation_output.investigation_target} for "
            f"{triage_output.incident_id}. Verifier status: {verifier_result.status}."
        )

    def _runner_status(
        self,
        branch: FollowUpBranch,
        verifier_status: VerifierStatus,
    ) -> AgentStatus:
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        if verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if branch is FollowUpBranch.NO_OP:
            return AgentStatus.COMPLETED
        return AgentStatus.RUNNING

    def _more_follow_up_required(
        self,
        branch: FollowUpBranch,
        verifier_status: VerifierStatus,
    ) -> bool:
        if verifier_status is not VerifierStatus.PASS:
            return True
        return branch is FollowUpBranch.INVESTIGATE

    def _no_op_reason(
        self,
        branch: FollowUpBranch,
        triage_was_verified_complete: bool,
        triage_output: IncidentTriageOutput,
    ) -> str | None:
        if branch is not FollowUpBranch.NO_OP:
            return None
        return (
            "Prior triage already passed verification and left no unresolved structured "
            "unknowns for "
            f"{triage_output.incident_id}: triage_verified={triage_was_verified_complete}."
        )
