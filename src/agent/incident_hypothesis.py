"""Resumable incident-hypothesis step built on evidence artifacts."""

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
)
from permissions.models import PermissionDecision
from permissions.policy import PermissionPolicy
from runtime.harness import (
    ResumableSliceHarness,
    combine_artifact_failure,
    pending_verifier_for_status,
)
from runtime.models import SyntheticFailure
from runtime.phases import HYPOTHESIS_STEP_ENTRY_PHASES
from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.incident_hypothesis import (
    IncidentHypothesisBuilderTool,
    IncidentHypothesisOutput,
)
from tools.models import ToolCall, ToolResult
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus
from verifiers.implementations.incident_hypothesis import (
    HypothesisBranch,
    IncidentHypothesisOutcomeVerifier,
)


class HypothesisResumeArtifacts(BaseModel):
    """Durable artifacts consulted by the incident-hypothesis step."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_path: Path
    transcript_path: Path
    previous_checkpoint_id: str
    previous_phase: str
    prior_transcript_event_count: int
    evidence_verifier_passed: bool


class IncidentHypothesisStepRequest(BaseModel):
    """Structured input for the incident-hypothesis continuation step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    resume_reason: str = "Continue from the latest evidence-reading artifacts."


class IncidentHypothesisStepResult(BaseModel):
    """Structured result returned by the incident-hypothesis step."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    incident_id: str
    resumed_successfully: bool
    branch: HypothesisBranch
    consulted_artifacts: HypothesisResumeArtifacts
    consumed_evidence_output: EvidenceReadOutput | None = None
    hypothesis_action_name: str | None = None
    verifier_name: str
    runner_status: AgentStatus
    evidence_supported: bool | None = None
    more_follow_up_required: bool
    verifier_result: VerifierResult
    permission_decision: PermissionDecision | None = None
    tool_result: ToolResult | None = None
    hypothesis_output: IncidentHypothesisOutput | None = None
    artifact_failure: SyntheticFailure | None = None
    checkpoint_path: Path
    checkpoint: SessionCheckpoint
    insufficiency_reason: str | None = None


@dataclass(slots=True)
class _HypothesisResumeContext:
    harness: ResumableSliceHarness
    artifact_context: SessionArtifactContext
    evidence_output: EvidenceReadOutput | None
    evidence_verifier_passed: bool
    evidence_failure: SyntheticFailure | None = None
    evidence_insufficiency_reason: str | None = None


@dataclass(slots=True)
class IncidentHypothesisStep:
    """Consumes one evidence record and builds one verifier-gated incident hypothesis."""

    transcript_root: Path = Path("sessions/transcripts")
    checkpoint_root: Path = Path("sessions/checkpoints")
    tool: IncidentHypothesisBuilderTool = field(default_factory=IncidentHypothesisBuilderTool)
    verifier: IncidentHypothesisOutcomeVerifier = field(
        default_factory=IncidentHypothesisOutcomeVerifier
    )
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)

    async def run(self, request: IncidentHypothesisStepRequest) -> IncidentHypothesisStepResult:
        context = self._load_context(request.session_id)
        harness = context.harness
        step_index = harness.step_index

        harness.emit_resume_started(reason=request.resume_reason)

        branch, insufficiency_reason = self._select_branch(context)
        evidence_output = context.evidence_output
        harness.emit_model_step(
            summary=self._model_step_summary(branch, context, evidence_output),
            planned_verifiers=[self.verifier.definition.name],
        )

        permission_decision: PermissionDecision | None = None
        tool_result: ToolResult | None = None
        hypothesis_output: IncidentHypothesisOutput | None = None

        if branch is HypothesisBranch.BUILD_HYPOTHESIS:
            if evidence_output is None:
                msg = "hypothesis branch requires a durable evidence record"
                raise RuntimeError(msg)

            tool_call = ToolCall(
                name=self.tool.definition.name,
                arguments={"evidence_output": evidence_output.model_dump(mode="json")},
            )
            tool_outcome = await harness.execute_read_only_tool(
                tool=self.tool,
                permission_policy=self.permission_policy,
                tool_call=tool_call,
                call_id=f"{request.session_id}-incident-hypothesis-tool",
                output_model=IncidentHypothesisOutput,
                permission_denied_message=(
                    "incident hypothesis tool must remain read-only and allowed by default"
                ),
            )
            permission_decision = tool_outcome.permission_decision
            tool_result = tool_outcome.tool_result
            hypothesis_output = tool_outcome.output

        verifier_request = VerifierRequest(
            name=self.verifier.definition.name,
            target=context.artifact_context.checkpoint.incident_id,
            inputs={
                "branch": branch,
                "evidence_phase": context.artifact_context.checkpoint.current_phase,
                "evidence_verifier_passed": context.evidence_verifier_passed,
                "insufficiency_reason": insufficiency_reason,
                "prior_artifact_failure": (
                    context.evidence_failure.model_dump(mode="json")
                    if context.evidence_failure is not None
                    else None
                ),
                "evidence_output": (
                    evidence_output.model_dump(mode="json")
                    if evidence_output is not None
                    else None
                ),
                "hypothesis_output": (
                    hypothesis_output.model_dump(mode="json")
                    if hypothesis_output is not None
                    else None
                ),
            },
        )
        verifier_result = await harness.execute_verifier(
            verifier=self.verifier,
            request=verifier_request,
        )
        artifact_failure = combine_artifact_failure(
            prior_failure=context.evidence_failure,
            tool_result=tool_result,
            verifier_result=verifier_result,
        )

        checkpoint = SessionCheckpoint(
            checkpoint_id=f"{request.session_id}-incident-hypothesis",
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            current_phase=self._current_phase(
                branch=branch,
                verifier_status=verifier_result.status,
                hypothesis_output=hypothesis_output,
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
                evidence_output=evidence_output,
                hypothesis_output=hypothesis_output,
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
        )

        return IncidentHypothesisStepResult(
            session_id=request.session_id,
            incident_id=context.artifact_context.checkpoint.incident_id,
            resumed_successfully=branch is HypothesisBranch.BUILD_HYPOTHESIS,
            branch=branch,
            consulted_artifacts=HypothesisResumeArtifacts(
                checkpoint_path=context.artifact_context.checkpoint_path,
                transcript_path=context.artifact_context.transcript_path,
                previous_checkpoint_id=context.artifact_context.checkpoint.checkpoint_id,
                previous_phase=context.artifact_context.checkpoint.current_phase,
                prior_transcript_event_count=len(context.artifact_context.transcript_events),
                evidence_verifier_passed=context.evidence_verifier_passed,
            ),
            consumed_evidence_output=evidence_output,
            hypothesis_action_name=(
                self.tool.definition.name if branch is HypothesisBranch.BUILD_HYPOTHESIS else None
            ),
            verifier_name=self.verifier.definition.name,
            runner_status=self._runner_status(
                branch,
                verifier_result.status,
                artifact_failure,
            ),
            evidence_supported=(
                hypothesis_output.evidence_supported if hypothesis_output is not None else None
            ),
            more_follow_up_required=self._more_follow_up_required(verifier_result.status),
            verifier_result=verifier_result,
            permission_decision=permission_decision,
            tool_result=tool_result,
            hypothesis_output=hypothesis_output,
            artifact_failure=artifact_failure,
            checkpoint_path=context.artifact_context.checkpoint_path,
            checkpoint=checkpoint,
            insufficiency_reason=insufficiency_reason,
        )

    def _load_context(self, session_id: str) -> _HypothesisResumeContext:
        harness = ResumableSliceHarness.load(
            session_id=session_id,
            step_name="incident_hypothesis",
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            working_memory_root=self._working_memory_root(),
        )
        artifact_context = harness.artifact_context
        artifact_context.require_current_phase_in(
            allowed_phases=HYPOTHESIS_STEP_ENTRY_PHASES,
            boundary_name="incident_hypothesis step entry",
        )
        evidence_resolution = artifact_context.evidence_output_for_hypothesis_step()
        evidence_record = artifact_context.latest_evidence_output()
        return _HypothesisResumeContext(
            harness=harness,
            artifact_context=artifact_context,
            evidence_output=evidence_resolution.artifact,
            evidence_verifier_passed=evidence_record.verifier_status is VerifierStatus.PASS,
            evidence_failure=evidence_resolution.failure,
            evidence_insufficiency_reason=evidence_resolution.reason,
        )

    def _select_branch(
        self,
        context: _HypothesisResumeContext,
    ) -> tuple[HypothesisBranch, str | None]:
        if context.evidence_output is not None:
            return HypothesisBranch.BUILD_HYPOTHESIS, None
        return (
            HypothesisBranch.INSUFFICIENT_STATE,
            context.evidence_insufficiency_reason
            or "Prior artifacts do not yet contain a verified evidence record.",
        )

    def _model_step_summary(
        self,
        branch: HypothesisBranch,
        context: _HypothesisResumeContext,
        evidence_output: EvidenceReadOutput | None,
    ) -> str:
        if branch is HypothesisBranch.BUILD_HYPOTHESIS and evidence_output is not None:
            return (
                f"Resume recovered evidence snapshot {evidence_output.snapshot_id} from "
                "durable artifacts and will build one deterministic incident hypothesis."
            )
        if context.evidence_failure is not None:
            return (
                "Resume found a structured evidence artifact failure in phase "
                f"{context.artifact_context.checkpoint.current_phase}, so the "
                "incident-hypothesis step will record a failure-aware insufficient-state branch."
            )
        return (
            "Resume did not find a usable verified evidence record in phase "
            f"{context.artifact_context.checkpoint.current_phase}, so the "
            "incident-hypothesis step will record "
            "an insufficient-state branch."
        )

    def _current_phase(
        self,
        branch: HypothesisBranch,
        verifier_status: VerifierStatus,
        hypothesis_output: IncidentHypothesisOutput | None,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return "hypothesis_failed_artifacts"
        if verifier_status is VerifierStatus.UNVERIFIED:
            return "hypothesis_unverified"
        if verifier_status is VerifierStatus.FAIL:
            return "hypothesis_failed_verification"
        if branch is HypothesisBranch.INSUFFICIENT_STATE:
            return "hypothesis_deferred"
        if hypothesis_output is None:
            return "hypothesis_unverified"
        if hypothesis_output.evidence_supported:
            return "hypothesis_supported"
        return "hypothesis_insufficient_evidence"

    def _progress_summary(
        self,
        branch: HypothesisBranch,
        evidence_output: EvidenceReadOutput | None,
        hypothesis_output: IncidentHypothesisOutput | None,
        verifier_result: VerifierResult,
        insufficiency_reason: str | None,
        artifact_failure: SyntheticFailure | None,
    ) -> str:
        if artifact_failure is not None:
            return (
                "Incident hypothesis step encountered a structured artifact failure: "
                f"{artifact_failure.reason} Verifier status: {verifier_result.status}."
            )
        if branch is HypothesisBranch.INSUFFICIENT_STATE:
            return (
                f"Incident hypothesis step deferred. Reason: {insufficiency_reason} "
                f"Verifier status: {verifier_result.status}."
            )
        if evidence_output is None or hypothesis_output is None:
            return (
                "Incident hypothesis step did not produce a structured hypothesis. "
                f"Verifier status: {verifier_result.status}."
            )
        return (
            f"Incident hypothesis step used snapshot {evidence_output.snapshot_id} and produced "
            f"{hypothesis_output.hypothesis_type}. Verifier status: {verifier_result.status}."
        )

    def _runner_status(
        self,
        branch: HypothesisBranch,
        verifier_status: VerifierStatus,
        artifact_failure: SyntheticFailure | None,
    ) -> AgentStatus:
        if artifact_failure is not None:
            return AgentStatus.FAILED
        if verifier_status is VerifierStatus.UNVERIFIED:
            return AgentStatus.VERIFYING
        if verifier_status is VerifierStatus.FAIL:
            return AgentStatus.FAILED
        if branch is HypothesisBranch.BUILD_HYPOTHESIS:
            return AgentStatus.RUNNING
        return AgentStatus.VERIFYING

    def _more_follow_up_required(self, verifier_status: VerifierStatus) -> bool:
        return True

    def _working_memory_root(self) -> Path:
        return self.checkpoint_root.parent / "working_memory"

    def _write_incident_working_memory(
        self,
        *,
        session_id: str,
        checkpoint: SessionCheckpoint,
        verifier_result: VerifierResult,
        hypothesis_output: IncidentHypothesisOutput | None,
    ) -> None:
        if verifier_result.status is not VerifierStatus.PASS or hypothesis_output is None:
            return

        JsonIncidentWorkingMemoryStore.for_incident(
            checkpoint.incident_id,
            root=self._working_memory_root(),
        ).write(
            IncidentWorkingMemory(
                incident_id=checkpoint.incident_id,
                service=hypothesis_output.service,
                source_session_id=session_id,
                source_checkpoint_id=checkpoint.checkpoint_id,
                source_phase=checkpoint.current_phase,
                last_updated_by_step="incident_hypothesis",
                leading_hypothesis=LeadingHypothesisSnapshot(
                    hypothesis_type=hypothesis_output.hypothesis_type,
                    summary=hypothesis_output.rationale_summary,
                    evidence_supported=hypothesis_output.evidence_supported,
                ),
                unresolved_gaps=hypothesis_output.unresolved_gaps,
                important_evidence_references=self._important_evidence_references(
                    hypothesis_output
                ),
                compact_handoff_note=self._compact_handoff_note(hypothesis_output),
            )
        )

    def _important_evidence_references(
        self,
        hypothesis_output: IncidentHypothesisOutput,
    ) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    f"evidence:{hypothesis_output.evidence_snapshot_id}",
                    f"investigation_target:{hypothesis_output.evidence_investigation_target}",
                    *[
                        f"field:{field_name}"
                        for field_name in hypothesis_output.supporting_evidence_fields
                    ],
                ]
            )
        )

    def _compact_handoff_note(
        self,
        hypothesis_output: IncidentHypothesisOutput,
    ) -> str:
        return (
            f"Current verified hypothesis for {hypothesis_output.service} is "
            f"{hypothesis_output.hypothesis_type}. "
            f"Rationale: {hypothesis_output.rationale_summary} "
            "No verified recommendation has been recorded yet."
        )
