from pathlib import Path

import pytest

from agent.incident_evidence import IncidentEvidenceStep, IncidentEvidenceStepRequest
from agent.incident_follow_up import IncidentFollowUpStep, IncidentFollowUpStepRequest
from agent.incident_hypothesis import IncidentHypothesisStep, IncidentHypothesisStepRequest
from agent.incident_recommendation import (
    IncidentRecommendationStep,
    IncidentRecommendationStepRequest,
)
from agent.incident_triage import IncidentTriageStep, IncidentTriageStepRequest
from context.handoff_artifact import JsonIncidentHandoffArtifactStore
from context.handoff_regeneration import (
    HandoffArtifactRegenerationStatus,
    IncidentHandoffArtifactRegenerator,
)
from memory.checkpoints import JsonCheckpointStore
from runtime.models import SyntheticFailureCode, SyntheticFailureSource
from runtime.phases import IncidentPhase


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


async def _run_chain_to_evidence(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
    recent_deployment: str | None = None,
) -> None:
    repo_root = _repository_root()
    triage_step = IncidentTriageStep(
        skills_root=repo_root / "skills",
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await triage_step.run(
        IncidentTriageStepRequest(
            session_id=session_id,
            incident_id=incident_id,
            title="Elevated 5xx errors on payments-api",
            service="payments-api",
            symptoms=["spike in 5xx", "checkout requests timing out"],
            impact_summary="Customer checkout requests are failing intermittently.",
            recent_deployment=recent_deployment,
        )
    )

    follow_up_step = IncidentFollowUpStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await follow_up_step.run(IncidentFollowUpStepRequest(session_id=session_id))

    evidence_step = IncidentEvidenceStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    evidence_step.tool.fixtures_path = repo_root / "evals/fixtures/evidence_snapshots.json"
    await evidence_step.run(IncidentEvidenceStepRequest(session_id=session_id))


async def _run_chain_to_recommendation(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
    recent_deployment: str | None = None,
) -> None:
    await _run_chain_to_evidence(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
        recent_deployment=recent_deployment,
    )

    hypothesis_step = IncidentHypothesisStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await hypothesis_step.run(IncidentHypothesisStepRequest(session_id=session_id))

    recommendation_step = IncidentRecommendationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await recommendation_step.run(IncidentRecommendationStepRequest(session_id=session_id))


async def _run_chain_to_hypothesis(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
    recent_deployment: str | None = None,
) -> None:
    await _run_chain_to_evidence(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
        recent_deployment=recent_deployment,
    )

    hypothesis_step = IncidentHypothesisStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await hypothesis_step.run(IncidentHypothesisStepRequest(session_id=session_id))


@pytest.mark.asyncio
async def test_handoff_regeneration_writes_artifact_from_recommendation_state(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-regen-recommendation"
    incident_id = "incident-handoff-regen-recommendation"
    await _run_chain_to_recommendation(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    regenerator = IncidentHandoffArtifactRegenerator(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    )
    result = regenerator.regenerate(session_id)

    assert result.status is HandoffArtifactRegenerationStatus.WRITTEN
    assert result.handoff_path is not None
    artifact = JsonIncidentHandoffArtifactStore(result.handoff_path).load()

    assert result.handoff_path == tmp_path / "handoffs" / f"{incident_id}.json"
    assert result.used_working_memory
    assert artifact.handoff == result.handoff_context
    assert artifact.handoff.current_phase == "recommendation_supported"
    assert artifact.handoff.recommendation_summary is not None


@pytest.mark.asyncio
async def test_handoff_regeneration_overwrites_existing_artifact_deterministically(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-regen-overwrite"
    incident_id = "incident-handoff-regen-overwrite"
    await _run_chain_to_recommendation(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    regenerator = IncidentHandoffArtifactRegenerator(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    )
    first_result = regenerator.regenerate(session_id)
    assert first_result.status is HandoffArtifactRegenerationStatus.WRITTEN
    assert first_result.handoff_path is not None
    assert not first_result.overwritten_existing
    original_contents = first_result.handoff_path.read_text(encoding="utf-8")

    first_result.handoff_path.write_text("stale\n", encoding="utf-8")
    second_result = regenerator.regenerate(session_id)

    assert second_result.status is HandoffArtifactRegenerationStatus.WRITTEN
    assert second_result.handoff_path is not None
    assert second_result.overwritten_existing
    assert second_result.handoff_path == first_result.handoff_path
    assert second_result.handoff_path.read_text(encoding="utf-8") == original_contents


@pytest.mark.asyncio
async def test_handoff_regeneration_succeeds_without_working_memory(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-regen-no-memory"
    incident_id = "incident-handoff-regen-no-memory"
    await _run_chain_to_evidence(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    regenerator = IncidentHandoffArtifactRegenerator(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    )
    result = regenerator.regenerate(session_id)

    assert result.status is HandoffArtifactRegenerationStatus.WRITTEN
    assert result.handoff_path is not None
    artifact = JsonIncidentHandoffArtifactStore(result.handoff_path).load()

    assert not result.used_working_memory
    assert artifact.handoff.current_phase == "evidence_reading_completed"
    assert artifact.handoff.leading_hypothesis_summary is None
    assert artifact.handoff.recommendation_summary is None


@pytest.mark.asyncio
async def test_handoff_regeneration_fails_when_phase_requires_missing_artifact(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-regen-missing-artifact"
    incident_id = "incident-handoff-regen-missing-artifact"
    await _run_chain_to_hypothesis(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    checkpoint_path = tmp_path / "checkpoints" / f"{session_id}.json"
    checkpoint_store = JsonCheckpointStore(checkpoint_path)
    checkpoint = checkpoint_store.load()
    mutated_checkpoint = checkpoint.model_copy(
        update={"current_phase": IncidentPhase.RECOMMENDATION_SUPPORTED}
    )
    checkpoint_store.write(mutated_checkpoint)

    regenerator = IncidentHandoffArtifactRegenerator(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    )
    result = regenerator.regenerate(session_id)

    assert result.status is HandoffArtifactRegenerationStatus.FAILED
    assert result.handoff_path is None
    assert result.required_artifact == "recommendation"
    assert result.artifact_failure is not None
    assert result.artifact_failure.code is SyntheticFailureCode.REQUIRED_ARTIFACT_UNUSABLE
    assert result.artifact_failure.source is SyntheticFailureSource.CONTEXT
    assert not (tmp_path / "handoffs" / f"{incident_id}.json").exists()
