"""Narrow regeneration seam for stable handoff artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from context.handoff import IncidentHandoffContext, IncidentHandoffContextAssembler
from context.handoff_artifact import (
    IncidentHandoffArtifactWriter,
    incident_handoff_artifact_path,
)
from context.session_artifacts import ArtifactResolution, SessionArtifactContext
from runtime.models import (
    SyntheticFailure,
    SyntheticFailureCode,
    SyntheticFailureSource,
)


class HandoffArtifactRegenerationStatus(StrEnum):
    """Stable outcomes for handoff-artifact regeneration."""

    WRITTEN = "written"
    INSUFFICIENT = "insufficient"
    FAILED = "failed"


class HandoffArtifactRegenerationResult(BaseModel):
    """Structured result from regenerating one handoff artifact."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    incident_id: str | None = None
    status: HandoffArtifactRegenerationStatus
    checkpoint_path: Path
    transcript_path: Path
    working_memory_path: Path | None = None
    handoff_path: Path | None = None
    overwritten_existing: bool = False
    used_working_memory: bool = False
    handoff_context: IncidentHandoffContext | None = None
    required_artifact: str | None = None
    insufficiency_reason: str | None = None
    artifact_failure: SyntheticFailure | None = None


@dataclass(slots=True)
class IncidentHandoffArtifactRegenerator:
    """Regenerate a stable handoff artifact from existing durable session state."""

    checkpoint_root: Path = Path("sessions/checkpoints")
    transcript_root: Path = Path("sessions/transcripts")
    working_memory_root: Path | None = None
    handoff_root: Path = Path("sessions/handoffs")
    assembler: IncidentHandoffContextAssembler = field(
        default_factory=IncidentHandoffContextAssembler
    )
    writer: IncidentHandoffArtifactWriter | None = None

    def __post_init__(self) -> None:
        if self.writer is None:
            self.writer = IncidentHandoffArtifactWriter(root=self.handoff_root)

    def regenerate(self, session_id: str) -> HandoffArtifactRegenerationResult:
        """Load current durable state and rewrite the latest handoff artifact."""

        checkpoint_path = self.checkpoint_root / f"{session_id}.json"
        transcript_path = self.transcript_root / f"{session_id}.jsonl"

        try:
            artifact_context = SessionArtifactContext.load(
                session_id,
                checkpoint_root=self.checkpoint_root,
                transcript_root=self.transcript_root,
                working_memory_root=self.working_memory_root,
            )
        except (FileNotFoundError, JSONDecodeError, ValidationError, ValueError) as exc:
            return HandoffArtifactRegenerationResult(
                session_id=session_id,
                status=HandoffArtifactRegenerationStatus.FAILED,
                checkpoint_path=checkpoint_path,
                transcript_path=transcript_path,
                artifact_failure=SyntheticFailure(
                    code=SyntheticFailureCode.REQUIRED_ARTIFACT_UNUSABLE,
                    source=SyntheticFailureSource.CONTEXT,
                    step_name="handoff_artifact_regeneration",
                    reason=(
                        "Handoff artifact regeneration could not load the required durable "
                        "session state."
                    ),
                    details={
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                ),
            )

        requirement = self._required_artifact_resolution(artifact_context)
        if requirement is not None:
            required_artifact, resolution = requirement
            if resolution.is_failure:
                return HandoffArtifactRegenerationResult(
                    session_id=session_id,
                    incident_id=artifact_context.checkpoint.incident_id,
                    status=HandoffArtifactRegenerationStatus.FAILED,
                    checkpoint_path=artifact_context.checkpoint_path,
                    transcript_path=artifact_context.transcript_path,
                    working_memory_path=artifact_context.working_memory_path,
                    required_artifact=required_artifact,
                    artifact_failure=resolution.failure,
                )
            if resolution.is_insufficient:
                return HandoffArtifactRegenerationResult(
                    session_id=session_id,
                    incident_id=artifact_context.checkpoint.incident_id,
                    status=HandoffArtifactRegenerationStatus.INSUFFICIENT,
                    checkpoint_path=artifact_context.checkpoint_path,
                    transcript_path=artifact_context.transcript_path,
                    working_memory_path=artifact_context.working_memory_path,
                    required_artifact=required_artifact,
                    insufficiency_reason=resolution.reason,
                )

        try:
            handoff_context = self.assembler.assemble(artifact_context)
            assert self.writer is not None
            handoff_path = incident_handoff_artifact_path(
                artifact_context.checkpoint.incident_id,
                root=self.writer.root,
            )
            overwritten_existing = handoff_path.exists()
            written_path = self.writer.write(
                artifact_context=artifact_context,
                handoff_context=handoff_context,
            )
        except (FileNotFoundError, ValidationError, OSError, ValueError) as exc:
            return HandoffArtifactRegenerationResult(
                session_id=session_id,
                incident_id=artifact_context.checkpoint.incident_id,
                status=HandoffArtifactRegenerationStatus.FAILED,
                checkpoint_path=artifact_context.checkpoint_path,
                transcript_path=artifact_context.transcript_path,
                working_memory_path=artifact_context.working_memory_path,
                artifact_failure=SyntheticFailure(
                    code=SyntheticFailureCode.REQUIRED_ARTIFACT_UNUSABLE,
                    source=SyntheticFailureSource.CONTEXT,
                    step_name="handoff_artifact_regeneration",
                    reason=(
                        "Handoff artifact regeneration could not assemble or write the "
                        "derived handoff artifact."
                    ),
                    details={
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    },
                ),
            )

        return HandoffArtifactRegenerationResult(
            session_id=session_id,
            incident_id=artifact_context.checkpoint.incident_id,
            status=HandoffArtifactRegenerationStatus.WRITTEN,
            checkpoint_path=artifact_context.checkpoint_path,
            transcript_path=artifact_context.transcript_path,
            working_memory_path=artifact_context.working_memory_path,
            handoff_path=written_path,
            overwritten_existing=overwritten_existing,
            used_working_memory=artifact_context.has_incident_working_memory(),
            handoff_context=handoff_context,
        )

    def _required_artifact_resolution(
        self,
        artifact_context: SessionArtifactContext,
    ) -> tuple[str, ArtifactResolution[Any]] | None:
        phase = artifact_context.checkpoint.current_phase

        if phase == "triage_completed":
            return "triage", artifact_context.latest_verified_triage_output()
        if phase == "follow_up_investigation_selected":
            return "follow_up", artifact_context.latest_verified_follow_up_output()
        if phase == "evidence_reading_completed":
            return "evidence", artifact_context.latest_verified_evidence_output()
        if phase in {"hypothesis_supported", "hypothesis_insufficient_evidence"}:
            return "hypothesis", artifact_context.latest_verified_hypothesis_output()
        if phase in {"recommendation_supported", "recommendation_conservative"}:
            return "recommendation", artifact_context.latest_verified_recommendation_output()
        if phase in {
            "action_stub_pending_approval",
            "action_stub_not_actionable",
            "action_stub_approved",
            "action_stub_denied",
        }:
            return "action_stub", artifact_context.latest_verified_action_stub_output()
        if phase in {
            "action_execution_completed",
            "action_execution_unverified",
            "action_execution_failed_verification",
            "action_execution_failed_artifacts",
            "action_execution_deferred",
        }:
            return "action_execution", artifact_context.latest_verified_action_execution_output()
        if phase in {
            "outcome_verification_succeeded",
            "outcome_verification_failed_verification",
            "outcome_verification_unverified",
            "outcome_verification_failed_artifacts",
        }:
            return (
                "outcome_verification",
                artifact_context.latest_verified_outcome_verification_output(),
            )
        return None
