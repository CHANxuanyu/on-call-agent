"""Shared context assembly for checkpoint and transcript-backed session artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from memory.checkpoints import JsonCheckpointStore, SessionCheckpoint
from memory.incident_working_memory import (
    IncidentWorkingMemory,
    JsonIncidentWorkingMemoryStore,
    incident_working_memory_path,
)
from runtime.models import (
    SyntheticFailure,
    SyntheticFailureCode,
    SyntheticFailureSource,
)
from tools.implementations.deployment_outcome_probe import DeploymentOutcomeProbeOutput
from tools.implementations.deployment_rollback import DeploymentRollbackExecutionOutput
from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.follow_up_investigation import (
    FollowUpInvestigationOutput,
    InvestigationTarget,
)
from tools.implementations.incident_action_stub import IncidentActionStubOutput
from tools.implementations.incident_hypothesis import IncidentHypothesisOutput
from tools.implementations.incident_recommendation import IncidentRecommendationOutput
from tools.implementations.incident_triage import IncidentTriageInput, IncidentTriageOutput
from transcripts.models import (
    ToolRequestEvent,
    ToolResultEvent,
    TranscriptEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierStatus

ArtifactModelT = TypeVar("ArtifactModelT", bound=BaseModel)
ArtifactValueT = TypeVar("ArtifactValueT")

_TRIAGE_TOOL_NAME = "incident_payload_summary"
_TRIAGE_VERIFIER_NAME = "incident_triage_output"
_FOLLOW_UP_TOOL_NAME = "investigation_focus_selector"
_FOLLOW_UP_VERIFIER_NAME = "incident_follow_up_outcome"
_EVIDENCE_TOOL_NAME = "evidence_bundle_reader"
_EVIDENCE_VERIFIER_NAME = "incident_evidence_read_outcome"
_HYPOTHESIS_TOOL_NAME = "incident_hypothesis_builder"
_HYPOTHESIS_VERIFIER_NAME = "incident_hypothesis_outcome"
_RECOMMENDATION_TOOL_NAME = "incident_recommendation_builder"
_RECOMMENDATION_VERIFIER_NAME = "incident_recommendation_outcome"
_ACTION_STUB_TOOL_NAME = "incident_action_stub_builder"
_ACTION_STUB_VERIFIER_NAME = "incident_action_stub_outcome"
_ACTION_EXECUTION_TOOL_NAME = "deployment_rollback_executor"
_ACTION_EXECUTION_VERIFIER_NAME = "deployment_rollback_execution"
_OUTCOME_VERIFICATION_TOOL_NAME = "deployment_outcome_probe"
_OUTCOME_VERIFICATION_VERIFIER_NAME = "deployment_outcome_verification"


class ArtifactKey(StrEnum):
    """Stable names for typed durable artifacts reconstructed from the session."""

    TRIAGE = "triage"
    FOLLOW_UP = "follow_up"
    EVIDENCE = "evidence"
    HYPOTHESIS = "hypothesis"
    RECOMMENDATION = "recommendation"
    ACTION_STUB = "action_stub"
    ACTION_EXECUTION = "action_execution"
    OUTCOME_VERIFICATION = "outcome_verification"


class ArtifactInsufficiencyCode(StrEnum):
    """Narrow reasons why a prior artifact cannot be used safely."""

    CHECKPOINT_PHASE_INCOMPATIBLE = "checkpoint_phase_incompatible"
    VERIFIER_NOT_PASSED = "verifier_not_passed"


class ArtifactInsufficiency(BaseModel):
    """Typed explanation for why a prior artifact is unavailable or unusable."""

    model_config = ConfigDict(extra="forbid")

    artifact: ArtifactKey
    code: ArtifactInsufficiencyCode
    message: str = Field(min_length=1)
    current_phase: str = Field(min_length=1)
    required_phases: tuple[str, ...] = ()
    tool_name: str = Field(min_length=1)
    verifier_name: str = Field(min_length=1)
    verifier_status: VerifierStatus | None = None
    invalid_output_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactRecord(Generic[ArtifactModelT]):
    """Latest transcript-backed record for one artifact type."""

    artifact: ArtifactKey
    tool_name: str
    verifier_name: str
    output: ArtifactModelT | None
    verifier_status: VerifierStatus | None
    synthetic_failure: SyntheticFailure | None = None
    invalid_output_detail: str | None = None

    @property
    def has_output(self) -> bool:
        return self.output is not None

    @property
    def is_verified(self) -> bool:
        return self.output is not None and self.verifier_status is VerifierStatus.PASS

    @property
    def has_failure(self) -> bool:
        return self.synthetic_failure is not None


@dataclass(frozen=True, slots=True)
class ArtifactResolution(Generic[ArtifactValueT]):
    """Resolved artifact plus an explicit insufficiency explanation when unavailable."""

    artifact: ArtifactValueT | None
    insufficiency: ArtifactInsufficiency | None = None
    failure: SyntheticFailure | None = None

    @property
    def is_available(self) -> bool:
        return (
            self.artifact is not None
            and self.insufficiency is None
            and self.failure is None
        )

    @property
    def is_success(self) -> bool:
        return self.is_available

    @property
    def is_failure(self) -> bool:
        return self.failure is not None

    @property
    def is_insufficient(self) -> bool:
        return self.insufficiency is not None

    @property
    def reason(self) -> str | None:
        if self.insufficiency is None:
            if self.failure is None:
                return None
            return self.failure.reason
        return self.insufficiency.message


@dataclass(frozen=True, slots=True)
class SessionArtifactContext:
    """Loads checkpoint and transcript once, then exposes typed durable artifacts."""

    session_id: str
    checkpoint_path: Path
    transcript_path: Path
    working_memory_path: Path
    checkpoint: SessionCheckpoint
    transcript_events: tuple[TranscriptEvent, ...]

    @classmethod
    def load(
        cls,
        session_id: str,
        *,
        checkpoint_root: Path = Path("sessions/checkpoints"),
        transcript_root: Path = Path("sessions/transcripts"),
        working_memory_root: Path | None = None,
    ) -> SessionArtifactContext:
        checkpoint_path = checkpoint_root / f"{session_id}.json"
        transcript_path = transcript_root / f"{session_id}.jsonl"
        checkpoint = JsonCheckpointStore(checkpoint_path).load()
        transcript_events = JsonlTranscriptStore(transcript_path).read_all()
        resolved_working_memory_root = (
            working_memory_root
            if working_memory_root is not None
            else checkpoint_root.parent / "working_memory"
        )
        return cls(
            session_id=session_id,
            checkpoint_path=checkpoint_path,
            transcript_path=transcript_path,
            working_memory_path=incident_working_memory_path(
                checkpoint.incident_id,
                root=resolved_working_memory_root,
            ),
            checkpoint=checkpoint,
            transcript_events=transcript_events,
        )

    def latest_incident_working_memory(self) -> IncidentWorkingMemory | None:
        """Return the latest local incident working-memory snapshot, if one exists."""

        return JsonIncidentWorkingMemoryStore(self.working_memory_path).load_optional()

    def latest_triage_input(self) -> IncidentTriageInput | None:
        """Return the latest structured triage input if it exists in the transcript."""

        tool_request_event = self._latest_tool_request_event(_TRIAGE_TOOL_NAME)
        if tool_request_event is None:
            return None
        try:
            return IncidentTriageInput.model_validate(tool_request_event[1].tool_call.arguments)
        except ValidationError:
            return None

    def has_incident_working_memory(self) -> bool:
        """Return whether a working-memory snapshot exists for the current incident."""

        return self.latest_incident_working_memory() is not None

    def phase_is(self, *phases: str) -> bool:
        """Return whether the current checkpoint phase matches one of the inputs."""

        return self.checkpoint.current_phase in phases

    def required_triage_output(self) -> ArtifactResolution[IncidentTriageOutput]:
        triage = self.latest_triage_output()
        if triage.synthetic_failure is not None:
            return ArtifactResolution(artifact=None, failure=triage.synthetic_failure)
        if triage.output is not None:
            return ArtifactResolution(artifact=triage.output)
        return ArtifactResolution(
            artifact=None,
            failure=self._context_failure(
                artifact=ArtifactKey.TRIAGE,
                code=SyntheticFailureCode.REQUIRED_ARTIFACT_UNUSABLE,
                reason="resume requires prior structured triage output in the transcript",
                tool_name=_TRIAGE_TOOL_NAME,
                verifier_name=_TRIAGE_VERIFIER_NAME,
                details={
                    "current_phase": self.checkpoint.current_phase,
                    "verifier_status": (
                        triage.verifier_status.value
                        if triage.verifier_status is not None
                        else "missing"
                    ),
                },
            ),
        )

    def latest_triage_output(self) -> ArtifactRecord[IncidentTriageOutput]:
        return self._artifact_record(
            artifact=ArtifactKey.TRIAGE,
            tool_name=_TRIAGE_TOOL_NAME,
            verifier_name=_TRIAGE_VERIFIER_NAME,
            model_type=IncidentTriageOutput,
        )

    def latest_verified_triage_output(self) -> ArtifactResolution[IncidentTriageOutput]:
        return self._require_verified_record(
            record=self.latest_triage_output(),
            missing_output_message=(
                "Triage artifacts indicate a verified triage record should exist, but the "
                "transcript is missing it."
            ),
            verifier_missing_message=(
                "Triage output exists in the transcript, but the verifier result is missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed triage record."
            ),
        )

    def has_verified_triage_output(self) -> bool:
        return self.latest_verified_triage_output().is_available

    def latest_follow_up_output(self) -> ArtifactRecord[FollowUpInvestigationOutput]:
        return self._artifact_record(
            artifact=ArtifactKey.FOLLOW_UP,
            tool_name=_FOLLOW_UP_TOOL_NAME,
            verifier_name=_FOLLOW_UP_VERIFIER_NAME,
            model_type=FollowUpInvestigationOutput,
        )

    def latest_follow_up_target(self) -> InvestigationTarget | None:
        follow_up = self.latest_follow_up_output().output
        if follow_up is None:
            return None
        return follow_up.investigation_target

    def latest_verified_follow_up_output(
        self,
    ) -> ArtifactResolution[FollowUpInvestigationOutput]:
        return self._require_verified_record(
            record=self.latest_follow_up_output(),
            missing_output_message=(
                "Follow-up artifacts indicate a selected target should exist, but the "
                "transcript is missing it."
            ),
            verifier_missing_message=(
                "Follow-up output exists in the transcript, but the verifier result is missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed follow-up "
                "investigation target."
            ),
        )

    def follow_up_output_for_evidence_step(
        self,
    ) -> ArtifactResolution[FollowUpInvestigationOutput]:
        if self.phase_is("follow_up_complete_no_action"):
            return ArtifactResolution(
                artifact=None,
                insufficiency=ArtifactInsufficiency(
                    artifact=ArtifactKey.FOLLOW_UP,
                    code=ArtifactInsufficiencyCode.CHECKPOINT_PHASE_INCOMPATIBLE,
                    message=(
                        "Previous follow-up step completed without selecting a further "
                        "investigation target."
                    ),
                    current_phase=self.checkpoint.current_phase,
                    required_phases=("follow_up_investigation_selected",),
                    tool_name=_FOLLOW_UP_TOOL_NAME,
                    verifier_name=_FOLLOW_UP_VERIFIER_NAME,
                    verifier_status=self.latest_follow_up_output().verifier_status,
                ),
            )

        return self._require_phase_compatible_verified_artifact(
            record=self.latest_follow_up_output(),
            compatible_phases=("follow_up_investigation_selected",),
            phase_incompatible_message=(
                "Prior artifacts do not yet contain a verified follow-up investigation target."
            ),
            missing_output_message=(
                "Follow-up artifacts indicate a selected target should exist, but the "
                "transcript is missing it."
            ),
            verifier_missing_message=(
                "Follow-up output exists in the transcript, but the verifier result is missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed follow-up "
                "investigation target."
            ),
        )

    def latest_verified_follow_up_target(
        self,
    ) -> ArtifactResolution[InvestigationTarget]:
        resolution = self.latest_verified_follow_up_output()
        if resolution.artifact is None:
            return ArtifactResolution(
                artifact=None,
                insufficiency=resolution.insufficiency,
                failure=resolution.failure,
            )
        return ArtifactResolution(artifact=resolution.artifact.investigation_target)

    def has_verified_follow_up_output(self) -> bool:
        return self.latest_verified_follow_up_output().is_available

    def latest_evidence_output(self) -> ArtifactRecord[EvidenceReadOutput]:
        return self._artifact_record(
            artifact=ArtifactKey.EVIDENCE,
            tool_name=_EVIDENCE_TOOL_NAME,
            verifier_name=_EVIDENCE_VERIFIER_NAME,
            model_type=EvidenceReadOutput,
        )

    def latest_verified_evidence_output(self) -> ArtifactResolution[EvidenceReadOutput]:
        return self._require_verified_record(
            record=self.latest_evidence_output(),
            missing_output_message=(
                "Evidence artifacts indicate a verified evidence record should exist, but the "
                "transcript is missing it."
            ),
            verifier_missing_message=(
                "Evidence output exists in the transcript, but the verifier result is missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed evidence record."
            ),
        )

    def evidence_output_for_hypothesis_step(self) -> ArtifactResolution[EvidenceReadOutput]:
        return self._require_phase_compatible_verified_artifact(
            record=self.latest_evidence_output(),
            compatible_phases=("evidence_reading_completed",),
            phase_incompatible_message=(
                "Prior artifacts do not yet contain a verified evidence record."
            ),
            missing_output_message=(
                "Evidence artifacts indicate a verified evidence record should exist, but the "
                "transcript is missing it."
            ),
            verifier_missing_message=(
                "Evidence output exists in the transcript, but the verifier result is missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed evidence record."
            ),
        )

    def has_verified_evidence_output(self) -> bool:
        return self.latest_verified_evidence_output().is_available

    def latest_hypothesis_output(self) -> ArtifactRecord[IncidentHypothesisOutput]:
        return self._artifact_record(
            artifact=ArtifactKey.HYPOTHESIS,
            tool_name=_HYPOTHESIS_TOOL_NAME,
            verifier_name=_HYPOTHESIS_VERIFIER_NAME,
            model_type=IncidentHypothesisOutput,
        )

    def latest_verified_hypothesis_output(
        self,
    ) -> ArtifactResolution[IncidentHypothesisOutput]:
        return self._require_verified_record(
            record=self.latest_hypothesis_output(),
            missing_output_message=(
                "Hypothesis artifacts indicate a verified hypothesis record should exist, but "
                "the transcript is missing it."
            ),
            verifier_missing_message=(
                "Hypothesis output exists in the transcript, but the verifier result is missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed incident hypothesis."
            ),
        )

    def hypothesis_output_for_recommendation_step(
        self,
    ) -> ArtifactResolution[IncidentHypothesisOutput]:
        return self._require_phase_compatible_verified_artifact(
            record=self.latest_hypothesis_output(),
            compatible_phases=("hypothesis_supported", "hypothesis_insufficient_evidence"),
            phase_incompatible_message=(
                "Prior artifacts do not yet contain a verified incident hypothesis."
            ),
            missing_output_message=(
                "Hypothesis artifacts indicate a verified hypothesis record should exist, but "
                "the transcript is missing it."
            ),
            verifier_missing_message=(
                "Hypothesis output exists in the transcript, but the verifier result is missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed incident hypothesis."
            ),
        )

    def has_verified_hypothesis_output(self) -> bool:
        return self.latest_verified_hypothesis_output().is_available

    def latest_recommendation_output(self) -> ArtifactRecord[IncidentRecommendationOutput]:
        return self._artifact_record(
            artifact=ArtifactKey.RECOMMENDATION,
            tool_name=_RECOMMENDATION_TOOL_NAME,
            verifier_name=_RECOMMENDATION_VERIFIER_NAME,
            model_type=IncidentRecommendationOutput,
        )

    def latest_verified_recommendation_output(
        self,
    ) -> ArtifactResolution[IncidentRecommendationOutput]:
        return self._require_verified_record(
            record=self.latest_recommendation_output(),
            missing_output_message=(
                "Recommendation artifacts indicate a verified recommendation record should "
                "exist, but the transcript is missing it."
            ),
            verifier_missing_message=(
                "Recommendation output exists in the transcript, but the verifier result is "
                "missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed recommendation record."
            ),
        )

    def recommendation_output_for_action_stub_step(
        self,
    ) -> ArtifactResolution[IncidentRecommendationOutput]:
        return self._require_phase_compatible_verified_artifact(
            record=self.latest_recommendation_output(),
            compatible_phases=("recommendation_supported", "recommendation_conservative"),
            phase_incompatible_message=(
                "Prior artifacts do not yet contain a verified recommendation record."
            ),
            missing_output_message=(
                "Recommendation artifacts indicate a verified recommendation record should "
                "exist, but the transcript is missing it."
            ),
            verifier_missing_message=(
                "Recommendation output exists in the transcript, but the verifier result is "
                "missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed recommendation record."
            ),
        )

    def has_verified_recommendation_output(self) -> bool:
        return self.latest_verified_recommendation_output().is_available

    def latest_action_stub_output(self) -> ArtifactRecord[IncidentActionStubOutput]:
        return self._artifact_record(
            artifact=ArtifactKey.ACTION_STUB,
            tool_name=_ACTION_STUB_TOOL_NAME,
            verifier_name=_ACTION_STUB_VERIFIER_NAME,
            model_type=IncidentActionStubOutput,
        )

    def latest_verified_action_stub_output(
        self,
    ) -> ArtifactResolution[IncidentActionStubOutput]:
        return self._require_verified_record(
            record=self.latest_action_stub_output(),
            missing_output_message=(
                "Action-stub artifacts indicate a verified action stub should exist, but the "
                "transcript is missing it."
            ),
            verifier_missing_message=(
                "Action-stub output exists in the transcript, but the verifier result is "
                "missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed action stub record."
            ),
        )

    def has_verified_action_stub_output(self) -> bool:
        return self.latest_verified_action_stub_output().is_available

    def latest_action_execution_output(
        self,
    ) -> ArtifactRecord[DeploymentRollbackExecutionOutput]:
        return self._artifact_record(
            artifact=ArtifactKey.ACTION_EXECUTION,
            tool_name=_ACTION_EXECUTION_TOOL_NAME,
            verifier_name=_ACTION_EXECUTION_VERIFIER_NAME,
            model_type=DeploymentRollbackExecutionOutput,
        )

    def latest_verified_action_execution_output(
        self,
    ) -> ArtifactResolution[DeploymentRollbackExecutionOutput]:
        return self._require_phase_compatible_verified_artifact(
            record=self.latest_action_execution_output(),
            compatible_phases=(
                "action_execution_completed",
                "outcome_verification_succeeded",
                "outcome_verification_failed_verification",
                "outcome_verification_unverified",
                "outcome_verification_failed_artifacts",
            ),
            phase_incompatible_message=(
                "Prior artifacts do not yet contain a verified rollback execution record."
            ),
            missing_output_message=(
                "Action-execution artifacts indicate a verified rollback execution should exist, "
                "but the transcript is missing it."
            ),
            verifier_missing_message=(
                "Rollback execution output exists in the transcript, but the verifier result is "
                "missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed rollback execution record."
            ),
        )

    def latest_outcome_verification_output(
        self,
    ) -> ArtifactRecord[DeploymentOutcomeProbeOutput]:
        return self._artifact_record(
            artifact=ArtifactKey.OUTCOME_VERIFICATION,
            tool_name=_OUTCOME_VERIFICATION_TOOL_NAME,
            verifier_name=_OUTCOME_VERIFICATION_VERIFIER_NAME,
            model_type=DeploymentOutcomeProbeOutput,
        )

    def latest_verified_outcome_verification_output(
        self,
    ) -> ArtifactResolution[DeploymentOutcomeProbeOutput]:
        return self._require_phase_compatible_verified_artifact(
            record=self.latest_outcome_verification_output(),
            compatible_phases=(
                "outcome_verification_succeeded",
                "outcome_verification_failed_verification",
                "outcome_verification_unverified",
                "outcome_verification_failed_artifacts",
            ),
            phase_incompatible_message=(
                "Prior artifacts do not yet contain a verified outcome verification record."
            ),
            missing_output_message=(
                "Outcome-verification artifacts indicate a verified runtime probe should exist, "
                "but the transcript is missing it."
            ),
            verifier_missing_message=(
                "Outcome-verification output exists in the transcript, but the verifier result is "
                "missing."
            ),
            verifier_not_passed_message=(
                "Prior artifacts do not yet contain a verifier-passed outcome verification "
                "record."
            ),
        )

    def _artifact_record(
        self,
        *,
        artifact: ArtifactKey,
        tool_name: str,
        verifier_name: str,
        model_type: type[ArtifactModelT],
    ) -> ArtifactRecord[ArtifactModelT]:
        tool_event = self._latest_tool_result_event(tool_name)
        tool_request_event = self._latest_tool_request_event(tool_name)
        output: ArtifactModelT | None = None
        invalid_output_detail: str | None = None
        synthetic_failure: SyntheticFailure | None = None
        if (
            tool_request_event is not None
            and (
                tool_event is None
                or tool_event[0] < tool_request_event[0]
            )
        ):
            latest_verifier_event = self._latest_verifier_result_event(verifier_name)
            if (
                latest_verifier_event is None
                or latest_verifier_event[0] < tool_request_event[0]
            ):
                synthetic_failure = SyntheticFailure(
                    code=SyntheticFailureCode.STEP_INTERRUPTED,
                    source=SyntheticFailureSource.STEP,
                    step_name=self._step_name_for_artifact(artifact),
                    tool_name=tool_name,
                    verifier_name=verifier_name,
                    reason=(
                        f"The latest {artifact.value.replace('_', ' ')} step emitted a tool "
                        "request but no matching tool result."
                    ),
                    details={"call_id": tool_request_event[1].call_id},
                )

        if tool_event is not None:
            tool_result_event = tool_event[1]
            if tool_result_event.result.failure is not None:
                synthetic_failure = (
                    tool_result_event.result.failure.synthetic_failure
                    or SyntheticFailure(
                        code=SyntheticFailureCode.TOOL_EXECUTION_FAILED,
                        source=SyntheticFailureSource.TOOL,
                        step_name=self._step_name_for_artifact(artifact),
                        tool_name=tool_name,
                        verifier_name=verifier_name,
                        reason=tool_result_event.result.failure.message,
                        details={
                            "tool_failure_code": tool_result_event.result.failure.code,
                            "call_id": tool_result_event.call_id,
                        },
                    )
                )
            elif tool_result_event.result.output:
                try:
                    output = model_type.model_validate(tool_result_event.result.output)
                except ValidationError as exc:
                    invalid_output_detail = str(exc)
                    synthetic_failure = SyntheticFailure(
                        code=SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED,
                        source=SyntheticFailureSource.TOOL,
                        step_name=self._step_name_for_artifact(artifact),
                        tool_name=tool_name,
                        verifier_name=verifier_name,
                        reason=(
                            f"{artifact.value.replace('_', ' ').title()} output exists in the "
                            "transcript but failed typed validation."
                        ),
                        details={
                            "validation_error": invalid_output_detail,
                            "call_id": tool_result_event.call_id,
                        },
                    )

        verifier_event = self._latest_verifier_result_event(verifier_name)
        verifier_status = verifier_event[1].result.status if verifier_event is not None else None
        if synthetic_failure is None and verifier_event is not None:
            synthetic_failure = verifier_event[1].result.synthetic_failure

        return ArtifactRecord(
            artifact=artifact,
            tool_name=tool_name,
            verifier_name=verifier_name,
            output=output,
            verifier_status=verifier_status,
            synthetic_failure=synthetic_failure,
            invalid_output_detail=invalid_output_detail,
        )

    def _require_verified_artifact(
        self,
        *,
        record: ArtifactRecord[ArtifactModelT],
        compatible_phases: tuple[str, ...],
        phase_incompatible_message: str,
        missing_output_message: str,
        verifier_missing_message: str,
        verifier_not_passed_message: str,
    ) -> ArtifactResolution[ArtifactModelT]:
        if not self.phase_is(*compatible_phases):
            return ArtifactResolution(
                artifact=None,
                insufficiency=ArtifactInsufficiency(
                    artifact=record.artifact,
                    code=ArtifactInsufficiencyCode.CHECKPOINT_PHASE_INCOMPATIBLE,
                    message=phase_incompatible_message,
                    current_phase=self.checkpoint.current_phase,
                    required_phases=compatible_phases,
                    tool_name=record.tool_name,
                    verifier_name=record.verifier_name,
                    verifier_status=record.verifier_status,
                ),
            )

        return self._require_verified_record(
            record=record,
            missing_output_message=missing_output_message,
            verifier_missing_message=verifier_missing_message,
            verifier_not_passed_message=verifier_not_passed_message,
            required_phases=compatible_phases,
        )

    def _require_phase_compatible_verified_artifact(
        self,
        *,
        record: ArtifactRecord[ArtifactModelT],
        compatible_phases: tuple[str, ...],
        phase_incompatible_message: str,
        missing_output_message: str,
        verifier_missing_message: str,
        verifier_not_passed_message: str,
    ) -> ArtifactResolution[ArtifactModelT]:
        return self._require_verified_artifact(
            record=record,
            compatible_phases=compatible_phases,
            phase_incompatible_message=phase_incompatible_message,
            missing_output_message=missing_output_message,
            verifier_missing_message=verifier_missing_message,
            verifier_not_passed_message=verifier_not_passed_message,
        )

    def _require_verified_record(
        self,
        *,
        record: ArtifactRecord[ArtifactModelT],
        missing_output_message: str,
        verifier_missing_message: str,
        verifier_not_passed_message: str,
        required_phases: tuple[str, ...] = (),
    ) -> ArtifactResolution[ArtifactModelT]:
        if record.synthetic_failure is not None:
            return ArtifactResolution(
                artifact=None,
                failure=record.synthetic_failure,
            )

        if record.invalid_output_detail is not None:
            return ArtifactResolution(
                artifact=None,
                failure=self._context_failure(
                    artifact=record.artifact,
                    code=SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED,
                    reason=(
                        f"{record.artifact.value.replace('_', ' ').title()} output exists in "
                        "the transcript but failed typed validation."
                    ),
                    tool_name=record.tool_name,
                    verifier_name=record.verifier_name,
                    details={
                        "current_phase": self.checkpoint.current_phase,
                        "validation_error": record.invalid_output_detail,
                    },
                ),
            )

        if record.output is None:
            return ArtifactResolution(
                artifact=None,
                failure=self._context_failure(
                    artifact=record.artifact,
                    code=SyntheticFailureCode.REQUIRED_ARTIFACT_UNUSABLE,
                    reason=missing_output_message,
                    tool_name=record.tool_name,
                    verifier_name=record.verifier_name,
                    details={
                        "current_phase": self.checkpoint.current_phase,
                        "required_phases": list(required_phases),
                    },
                ),
            )

        if record.verifier_status is None:
            return ArtifactResolution(
                artifact=None,
                failure=self._context_failure(
                    artifact=record.artifact,
                    code=SyntheticFailureCode.VERIFIER_RESULT_MISSING,
                    reason=verifier_missing_message,
                    tool_name=record.tool_name,
                    verifier_name=record.verifier_name,
                    details={
                        "current_phase": self.checkpoint.current_phase,
                        "required_phases": list(required_phases),
                    },
                ),
            )

        if record.verifier_status is not VerifierStatus.PASS:
            return ArtifactResolution(
                artifact=None,
                insufficiency=ArtifactInsufficiency(
                    artifact=record.artifact,
                    code=ArtifactInsufficiencyCode.VERIFIER_NOT_PASSED,
                    message=verifier_not_passed_message,
                    current_phase=self.checkpoint.current_phase,
                    required_phases=required_phases,
                    tool_name=record.tool_name,
                    verifier_name=record.verifier_name,
                    verifier_status=record.verifier_status,
                ),
            )

        return ArtifactResolution(artifact=record.output)

    def _latest_tool_request_event(
        self,
        tool_name: str,
    ) -> tuple[int, ToolRequestEvent] | None:
        for index in range(len(self.transcript_events) - 1, -1, -1):
            event = self.transcript_events[index]
            if isinstance(event, ToolRequestEvent) and event.tool_call.name == tool_name:
                return index, event
        return None

    def _latest_tool_result_event(
        self,
        tool_name: str,
    ) -> tuple[int, ToolResultEvent] | None:
        for index in range(len(self.transcript_events) - 1, -1, -1):
            event = self.transcript_events[index]
            if isinstance(event, ToolResultEvent) and event.tool_name == tool_name:
                return index, event
        return None

    def _latest_verifier_result_event(
        self,
        verifier_name: str,
    ) -> tuple[int, VerifierResultEvent] | None:
        for index in range(len(self.transcript_events) - 1, -1, -1):
            event = self.transcript_events[index]
            if (
                isinstance(event, VerifierResultEvent)
                and event.verifier_name == verifier_name
            ):
                return index, event
        return None

    def _context_failure(
        self,
        *,
        artifact: ArtifactKey,
        code: SyntheticFailureCode,
        reason: str,
        tool_name: str,
        verifier_name: str,
        details: dict[str, object] | None = None,
    ) -> SyntheticFailure:
        return SyntheticFailure(
            code=code,
            source=SyntheticFailureSource.CONTEXT,
            step_name=self._step_name_for_artifact(artifact),
            tool_name=tool_name,
            verifier_name=verifier_name,
            reason=reason,
            details=details or {},
        )

    def _step_name_for_artifact(self, artifact: ArtifactKey) -> str:
        return {
            ArtifactKey.TRIAGE: "incident_triage",
            ArtifactKey.FOLLOW_UP: "incident_follow_up",
            ArtifactKey.EVIDENCE: "incident_evidence",
            ArtifactKey.HYPOTHESIS: "incident_hypothesis",
            ArtifactKey.RECOMMENDATION: "incident_recommendation",
            ArtifactKey.ACTION_STUB: "incident_action_stub",
            ArtifactKey.ACTION_EXECUTION: "deployment_rollback_execution",
            ArtifactKey.OUTCOME_VERIFICATION: "deployment_outcome_verification",
        }[artifact]
