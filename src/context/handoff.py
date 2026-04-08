"""Read-only operator-facing handoff context assembly."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import ApprovalState, ApprovalStatus
from memory.incident_working_memory import IncidentWorkingMemory
from runtime.phases import IncidentPhase
from tools.implementations.deployment_outcome_probe import DeploymentOutcomeProbeOutput
from tools.implementations.deployment_rollback import DeploymentRollbackExecutionOutput
from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.follow_up_investigation import FollowUpInvestigationOutput
from tools.implementations.incident_action_stub import IncidentActionStubOutput
from tools.implementations.incident_hypothesis import IncidentHypothesisOutput
from tools.implementations.incident_recommendation import IncidentRecommendationOutput
from tools.implementations.incident_triage import IncidentTriageOutput


class HandoffArtifactSource(StrEnum):
    """Durable sources consulted during handoff assembly."""

    CHECKPOINT = "checkpoint"
    VERIFIED_TRANSCRIPT_ARTIFACT = "verified_transcript_artifact"
    INCIDENT_WORKING_MEMORY = "incident_working_memory"


class HandoffArtifactReference(BaseModel):
    """Reference to one durable artifact consulted by the handoff assembler."""

    model_config = ConfigDict(extra="forbid")

    source: HandoffArtifactSource
    artifact_name: str = Field(min_length=1)
    path: Path
    detail: str | None = None


class ApprovalHandoffSummary(BaseModel):
    """Compact approval-state summary for operator-facing handoff context."""

    model_config = ConfigDict(extra="forbid")

    status: ApprovalStatus
    requested_action: str | None = None
    reason: str | None = None
    future_preconditions: list[str] = Field(default_factory=list)
    summary: str | None = None


class IncidentHandoffContext(BaseModel):
    """Compact operator-facing context assembled from durable runtime artifacts."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    service: str | None = None
    current_phase: IncidentPhase
    progress_summary: str = Field(min_length=1)
    leading_hypothesis_summary: str | None = None
    recommendation_summary: str | None = None
    unresolved_gaps: list[str] = Field(default_factory=list)
    important_evidence_references: list[str] = Field(default_factory=list)
    approval: ApprovalHandoffSummary
    current_operator_attention_point: str = Field(min_length=1)
    compact_handoff_note: str = Field(min_length=1)
    derived_from: list[HandoffArtifactReference] = Field(min_length=1)


@dataclass(slots=True)
class IncidentHandoffContextAssembler:
    """Assemble one read-only handoff summary from checkpoint, transcripts, and memory."""

    def assemble(self, artifact_context: SessionArtifactContext) -> IncidentHandoffContext:
        triage_output = artifact_context.latest_verified_triage_output().artifact
        follow_up_output = artifact_context.latest_verified_follow_up_output().artifact
        evidence_output = artifact_context.latest_verified_evidence_output().artifact
        hypothesis_output = artifact_context.latest_verified_hypothesis_output().artifact
        recommendation_output = artifact_context.latest_verified_recommendation_output().artifact
        action_stub_output = artifact_context.latest_verified_action_stub_output().artifact
        action_execution_output = (
            artifact_context.latest_verified_action_execution_output().artifact
        )
        outcome_verification_output = (
            artifact_context.latest_verified_outcome_verification_output().artifact
        )
        working_memory = artifact_context.latest_incident_working_memory()

        approval = self._approval_summary(artifact_context.checkpoint.approval_state)
        service = self._service(
            triage_output=triage_output,
            follow_up_output=follow_up_output,
            evidence_output=evidence_output,
            hypothesis_output=hypothesis_output,
            recommendation_output=recommendation_output,
            action_stub_output=action_stub_output,
            action_execution_output=action_execution_output,
            outcome_verification_output=outcome_verification_output,
            working_memory=working_memory,
        )
        leading_hypothesis_summary = self._leading_hypothesis_summary(
            hypothesis_output=hypothesis_output,
            working_memory=working_memory,
        )
        recommendation_summary = self._recommendation_summary(
            recommendation_output=recommendation_output,
            working_memory=working_memory,
        )
        unresolved_gaps = self._unresolved_gaps(
            checkpoint_phase=artifact_context.checkpoint.current_phase,
            hypothesis_output=hypothesis_output,
            outcome_verification_output=outcome_verification_output,
            working_memory=working_memory,
        )
        important_evidence_references = self._important_evidence_references(
            evidence_output=evidence_output,
            hypothesis_output=hypothesis_output,
            recommendation_output=recommendation_output,
            action_stub_output=action_stub_output,
            action_execution_output=action_execution_output,
            outcome_verification_output=outcome_verification_output,
            working_memory=working_memory,
        )
        current_operator_attention_point = self._operator_attention_point(
            checkpoint_approval=artifact_context.checkpoint.approval_state,
            triage_output=triage_output,
            follow_up_output=follow_up_output,
            evidence_output=evidence_output,
            hypothesis_output=hypothesis_output,
            recommendation_output=recommendation_output,
            action_stub_output=action_stub_output,
            action_execution_output=action_execution_output,
            outcome_verification_output=outcome_verification_output,
            working_memory=working_memory,
            progress_summary=artifact_context.checkpoint.summary_of_progress,
        )
        compact_handoff_note = self._compact_handoff_note(
            checkpoint_phase=artifact_context.checkpoint.current_phase,
            progress_summary=artifact_context.checkpoint.summary_of_progress,
            approval=approval,
            leading_hypothesis_summary=leading_hypothesis_summary,
            recommendation_summary=recommendation_summary,
            current_operator_attention_point=current_operator_attention_point,
            working_memory=working_memory,
        )

        return IncidentHandoffContext(
            incident_id=artifact_context.checkpoint.incident_id,
            service=service,
            current_phase=artifact_context.checkpoint.current_phase,
            progress_summary=artifact_context.checkpoint.summary_of_progress,
            leading_hypothesis_summary=leading_hypothesis_summary,
            recommendation_summary=recommendation_summary,
            unresolved_gaps=unresolved_gaps,
            important_evidence_references=important_evidence_references,
            approval=approval,
            current_operator_attention_point=current_operator_attention_point,
            compact_handoff_note=compact_handoff_note,
            derived_from=self._derived_from(
                artifact_context=artifact_context,
                triage_output=triage_output,
                follow_up_output=follow_up_output,
                evidence_output=evidence_output,
                hypothesis_output=hypothesis_output,
                recommendation_output=recommendation_output,
                action_stub_output=action_stub_output,
                action_execution_output=action_execution_output,
                outcome_verification_output=outcome_verification_output,
                working_memory=working_memory,
            ),
        )

    def load_and_assemble(
        self,
        session_id: str,
        *,
        checkpoint_root: Path = Path("sessions/checkpoints"),
        transcript_root: Path = Path("sessions/transcripts"),
        working_memory_root: Path | None = None,
    ) -> IncidentHandoffContext:
        """Convenience helper for read-only handoff assembly from a session id."""

        artifact_context = SessionArtifactContext.load(
            session_id,
            checkpoint_root=checkpoint_root,
            transcript_root=transcript_root,
            working_memory_root=working_memory_root,
        )
        return self.assemble(artifact_context)

    def _approval_summary(self, approval_state: ApprovalState) -> ApprovalHandoffSummary:
        if approval_state.status is ApprovalStatus.PENDING:
            requested_action = approval_state.requested_action or "pending_action"
            summary = f"Pending approval for {requested_action}."
            if approval_state.reason:
                summary = f"{summary} {approval_state.reason}"
            return ApprovalHandoffSummary(
                status=approval_state.status,
                requested_action=approval_state.requested_action,
                reason=approval_state.reason,
                future_preconditions=approval_state.future_preconditions,
                summary=summary,
            )

        if approval_state.status is ApprovalStatus.APPROVED:
            summary = "Approval has been recorded."
            if approval_state.reason:
                summary = f"{summary} {approval_state.reason}"
            return ApprovalHandoffSummary(
                status=approval_state.status,
                requested_action=approval_state.requested_action,
                reason=approval_state.reason,
                future_preconditions=approval_state.future_preconditions,
                summary=summary,
            )

        if approval_state.status is ApprovalStatus.DENIED:
            summary = "Approval was denied."
            if approval_state.reason:
                summary = f"{summary} {approval_state.reason}"
            return ApprovalHandoffSummary(
                status=approval_state.status,
                requested_action=approval_state.requested_action,
                reason=approval_state.reason,
                future_preconditions=approval_state.future_preconditions,
                summary=summary,
            )

        return ApprovalHandoffSummary(
            status=approval_state.status,
            requested_action=approval_state.requested_action,
            reason=approval_state.reason,
            future_preconditions=approval_state.future_preconditions,
            summary=approval_state.reason,
        )

    def _service(
        self,
        *,
        triage_output: IncidentTriageOutput | None,
        follow_up_output: FollowUpInvestigationOutput | None,
        evidence_output: EvidenceReadOutput | None,
        hypothesis_output: IncidentHypothesisOutput | None,
        recommendation_output: IncidentRecommendationOutput | None,
        action_stub_output: IncidentActionStubOutput | None,
        action_execution_output: DeploymentRollbackExecutionOutput | None,
        outcome_verification_output: DeploymentOutcomeProbeOutput | None,
        working_memory: IncidentWorkingMemory | None,
    ) -> str | None:
        return next(
            (
                service
                for service in (
                    outcome_verification_output.service
                    if outcome_verification_output is not None
                    else None,
                    action_execution_output.service
                    if action_execution_output is not None
                    else None,
                    action_stub_output.service if action_stub_output is not None else None,
                    recommendation_output.service
                    if recommendation_output is not None
                    else None,
                    hypothesis_output.service if hypothesis_output is not None else None,
                    evidence_output.service if evidence_output is not None else None,
                    follow_up_output.service if follow_up_output is not None else None,
                    triage_output.service if triage_output is not None else None,
                    working_memory.service if working_memory is not None else None,
                )
                if service is not None
            ),
            None,
        )

    def _leading_hypothesis_summary(
        self,
        *,
        hypothesis_output: IncidentHypothesisOutput | None,
        working_memory: IncidentWorkingMemory | None,
    ) -> str | None:
        if hypothesis_output is not None:
            return hypothesis_output.rationale_summary
        if working_memory is None or working_memory.leading_hypothesis is None:
            return None
        return working_memory.leading_hypothesis.summary

    def _recommendation_summary(
        self,
        *,
        recommendation_output: IncidentRecommendationOutput | None,
        working_memory: IncidentWorkingMemory | None,
    ) -> str | None:
        if recommendation_output is not None:
            return recommendation_output.action_summary
        if working_memory is None or working_memory.recommendation is None:
            return None
        return working_memory.recommendation.summary

    def _unresolved_gaps(
        self,
        *,
        checkpoint_phase: IncidentPhase,
        hypothesis_output: IncidentHypothesisOutput | None,
        outcome_verification_output: DeploymentOutcomeProbeOutput | None,
        working_memory: IncidentWorkingMemory | None,
    ) -> list[str]:
        if (
            working_memory is not None
            and working_memory.source_phase == checkpoint_phase
        ):
            return working_memory.unresolved_gaps
        if (
            checkpoint_phase is IncidentPhase.OUTCOME_VERIFICATION_SUCCEEDED
            and outcome_verification_output is not None
        ):
            return []
        if hypothesis_output is not None and hypothesis_output.unresolved_gaps:
            return hypothesis_output.unresolved_gaps
        if working_memory is None:
            return []
        return working_memory.unresolved_gaps

    def _important_evidence_references(
        self,
        *,
        evidence_output: EvidenceReadOutput | None,
        hypothesis_output: IncidentHypothesisOutput | None,
        recommendation_output: IncidentRecommendationOutput | None,
        action_stub_output: IncidentActionStubOutput | None,
        action_execution_output: DeploymentRollbackExecutionOutput | None,
        outcome_verification_output: DeploymentOutcomeProbeOutput | None,
        working_memory: IncidentWorkingMemory | None,
    ) -> list[str]:
        ordered_refs: list[str] = []
        for ref in (
            action_stub_output.supporting_artifact_refs if action_stub_output is not None else []
        ):
            if ref not in ordered_refs:
                ordered_refs.append(ref)
        for ref in (
            recommendation_output.supporting_artifact_refs
            if recommendation_output is not None
            else []
        ):
            if ref not in ordered_refs:
                ordered_refs.append(ref)
        if hypothesis_output is not None:
            for ref in (
                f"hypothesis:{hypothesis_output.hypothesis_type}",
                f"evidence:{hypothesis_output.evidence_snapshot_id}",
                *(
                    f"field:{field_name}"
                    for field_name in hypothesis_output.supporting_evidence_fields
                ),
            ):
                if ref not in ordered_refs:
                    ordered_refs.append(ref)
        if evidence_output is not None:
            for ref in (
                f"evidence:{evidence_output.snapshot_id}",
                evidence_output.evidence_source,
            ):
                if ref not in ordered_refs:
                    ordered_refs.append(ref)
        if working_memory is not None:
            for ref in working_memory.important_evidence_references:
                if ref not in ordered_refs:
                    ordered_refs.append(ref)
        if action_execution_output is not None:
            for ref in (
                f"rollback:{action_execution_output.observed_version_before}->"
                f"{action_execution_output.observed_version_after}",
                action_execution_output.service_base_url,
            ):
                if ref not in ordered_refs:
                    ordered_refs.append(ref)
        if outcome_verification_output is not None:
            for ref in outcome_verification_output.evidence_refs:
                if ref not in ordered_refs:
                    ordered_refs.append(ref)
        return ordered_refs

    def _operator_attention_point(
        self,
        *,
        checkpoint_approval: ApprovalState,
        triage_output: IncidentTriageOutput | None,
        follow_up_output: FollowUpInvestigationOutput | None,
        evidence_output: EvidenceReadOutput | None,
        hypothesis_output: IncidentHypothesisOutput | None,
        recommendation_output: IncidentRecommendationOutput | None,
        action_stub_output: IncidentActionStubOutput | None,
        action_execution_output: DeploymentRollbackExecutionOutput | None,
        outcome_verification_output: DeploymentOutcomeProbeOutput | None,
        working_memory: IncidentWorkingMemory | None,
        progress_summary: str,
    ) -> str:
        if checkpoint_approval.status is ApprovalStatus.PENDING:
            requested_action = checkpoint_approval.requested_action or "pending action"
            return (
                f"Review the approval gate for {requested_action} and confirm the "
                "recorded future preconditions still hold."
            )
        if outcome_verification_output is not None:
            return outcome_verification_output.summary
        if action_execution_output is not None:
            return action_execution_output.execution_summary
        if action_stub_output is not None:
            return action_stub_output.action_summary
        if recommendation_output is not None:
            return recommendation_output.action_summary
        if hypothesis_output is not None:
            return hypothesis_output.recommended_next_action
        if evidence_output is not None:
            return evidence_output.recommended_next_read_only_action
        if follow_up_output is not None:
            return follow_up_output.recommended_read_only_action
        if triage_output is not None:
            return triage_output.recommended_next_action
        if working_memory is not None:
            return working_memory.compact_handoff_note
        return progress_summary

    def _compact_handoff_note(
        self,
        *,
        checkpoint_phase: IncidentPhase,
        progress_summary: str,
        approval: ApprovalHandoffSummary,
        leading_hypothesis_summary: str | None,
        recommendation_summary: str | None,
        current_operator_attention_point: str,
        working_memory: IncidentWorkingMemory | None,
    ) -> str:
        if (
            working_memory is not None
            and working_memory.source_phase == checkpoint_phase
        ):
            return working_memory.compact_handoff_note

        note_parts = [
            f"Current phase is {checkpoint_phase}.",
            progress_summary,
        ]
        if leading_hypothesis_summary is not None:
            note_parts.append(f"Leading hypothesis: {leading_hypothesis_summary}")
        if recommendation_summary is not None:
            note_parts.append(f"Recommendation: {recommendation_summary}")
        if approval.summary is not None:
            note_parts.append(approval.summary)
        note_parts.append(
            f"Current operator attention point: {current_operator_attention_point}"
        )
        return " ".join(note_parts)

    def _derived_from(
        self,
        *,
        artifact_context: SessionArtifactContext,
        triage_output: IncidentTriageOutput | None,
        follow_up_output: FollowUpInvestigationOutput | None,
        evidence_output: EvidenceReadOutput | None,
        hypothesis_output: IncidentHypothesisOutput | None,
        recommendation_output: IncidentRecommendationOutput | None,
        action_stub_output: IncidentActionStubOutput | None,
        action_execution_output: DeploymentRollbackExecutionOutput | None,
        outcome_verification_output: DeploymentOutcomeProbeOutput | None,
        working_memory: IncidentWorkingMemory | None,
    ) -> list[HandoffArtifactReference]:
        references: list[HandoffArtifactReference] = []
        seen: set[tuple[HandoffArtifactSource, str, str]] = set()

        def add_reference(reference: HandoffArtifactReference) -> None:
            key = (
                reference.source,
                reference.artifact_name,
                str(reference.path),
            )
            if key in seen:
                return
            seen.add(key)
            references.append(reference)

        add_reference(
            HandoffArtifactReference(
                source=HandoffArtifactSource.CHECKPOINT,
                artifact_name="session_checkpoint",
                path=artifact_context.checkpoint_path,
                detail=artifact_context.checkpoint.checkpoint_id,
            )
        )
        if triage_output is not None:
            add_reference(
                HandoffArtifactReference(
                    source=HandoffArtifactSource.VERIFIED_TRANSCRIPT_ARTIFACT,
                    artifact_name="incident_triage_output",
                    path=artifact_context.transcript_path,
                    detail=triage_output.incident_id,
                )
            )
        if follow_up_output is not None:
            add_reference(
                HandoffArtifactReference(
                    source=HandoffArtifactSource.VERIFIED_TRANSCRIPT_ARTIFACT,
                    artifact_name="follow_up_investigation_output",
                    path=artifact_context.transcript_path,
                    detail=follow_up_output.investigation_target,
                )
            )
        if evidence_output is not None:
            add_reference(
                HandoffArtifactReference(
                    source=HandoffArtifactSource.VERIFIED_TRANSCRIPT_ARTIFACT,
                    artifact_name="evidence_read_output",
                    path=artifact_context.transcript_path,
                    detail=evidence_output.snapshot_id,
                )
            )
        if hypothesis_output is not None:
            add_reference(
                HandoffArtifactReference(
                    source=HandoffArtifactSource.VERIFIED_TRANSCRIPT_ARTIFACT,
                    artifact_name="incident_hypothesis_output",
                    path=artifact_context.transcript_path,
                    detail=hypothesis_output.hypothesis_type,
                )
            )
        if recommendation_output is not None:
            add_reference(
                HandoffArtifactReference(
                    source=HandoffArtifactSource.VERIFIED_TRANSCRIPT_ARTIFACT,
                    artifact_name="incident_recommendation_output",
                    path=artifact_context.transcript_path,
                    detail=recommendation_output.recommendation_type,
                )
            )
        if action_stub_output is not None:
            add_reference(
                HandoffArtifactReference(
                    source=HandoffArtifactSource.VERIFIED_TRANSCRIPT_ARTIFACT,
                    artifact_name="incident_action_stub_output",
                    path=artifact_context.transcript_path,
                    detail=action_stub_output.action_candidate_type,
                )
            )
        if action_execution_output is not None:
            add_reference(
                HandoffArtifactReference(
                    source=HandoffArtifactSource.VERIFIED_TRANSCRIPT_ARTIFACT,
                    artifact_name="deployment_rollback_execution_output",
                    path=artifact_context.transcript_path,
                    detail=action_execution_output.execution_summary,
                )
            )
        if outcome_verification_output is not None:
            add_reference(
                HandoffArtifactReference(
                    source=HandoffArtifactSource.VERIFIED_TRANSCRIPT_ARTIFACT,
                    artifact_name="deployment_outcome_probe_output",
                    path=artifact_context.transcript_path,
                    detail=outcome_verification_output.summary,
                )
            )
        if working_memory is not None:
            add_reference(
                HandoffArtifactReference(
                    source=HandoffArtifactSource.INCIDENT_WORKING_MEMORY,
                    artifact_name="incident_working_memory",
                    path=artifact_context.working_memory_path,
                    detail=working_memory.source_phase,
                )
            )
        return references
