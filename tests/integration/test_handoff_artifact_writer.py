from pathlib import Path

import pytest

from agent.incident_action_stub import (
    IncidentActionStubStep,
    IncidentActionStubStepRequest,
)
from agent.incident_evidence import IncidentEvidenceStep, IncidentEvidenceStepRequest
from agent.incident_follow_up import IncidentFollowUpStep, IncidentFollowUpStepRequest
from agent.incident_hypothesis import IncidentHypothesisStep, IncidentHypothesisStepRequest
from agent.incident_recommendation import (
    IncidentRecommendationStep,
    IncidentRecommendationStepRequest,
)
from agent.incident_triage import IncidentTriageStep, IncidentTriageStepRequest
from context.handoff import HandoffArtifactSource, IncidentHandoffContextAssembler
from context.handoff_artifact import (
    IncidentHandoffArtifactWriter,
    JsonIncidentHandoffArtifactStore,
)
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import ApprovalStatus


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


async def _run_chain_to_action_stub(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
    recent_deployment: str | None = None,
) -> None:
    await _run_chain_to_recommendation(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
        recent_deployment=recent_deployment,
    )

    action_stub_step = IncidentActionStubStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await action_stub_step.run(IncidentActionStubStepRequest(session_id=session_id))


@pytest.mark.asyncio
async def test_handoff_artifact_writer_writes_recommendation_snapshot_with_working_memory(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-artifact-recommendation"
    incident_id = "incident-handoff-artifact-recommendation"
    await _run_chain_to_recommendation(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    artifact_context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )
    handoff_context = IncidentHandoffContextAssembler().assemble(artifact_context)
    writer = IncidentHandoffArtifactWriter(root=tmp_path / "handoffs")

    path = writer.write(
        artifact_context=artifact_context,
        handoff_context=handoff_context,
    )
    artifact = JsonIncidentHandoffArtifactStore(path).load()

    assert path == (tmp_path / "handoffs" / f"{incident_id}.json")
    assert artifact.source_session_id == session_id
    assert artifact.source_checkpoint_id == artifact_context.checkpoint.checkpoint_id
    assert artifact.source_checkpoint_time == artifact_context.checkpoint.latest_checkpoint_time
    assert artifact.handoff == handoff_context
    assert artifact.handoff.current_phase == "recommendation_supported"
    assert artifact.handoff.recommendation_summary is not None
    assert any(
        reference.source is HandoffArtifactSource.INCIDENT_WORKING_MEMORY
        for reference in artifact.handoff.derived_from
    )


@pytest.mark.asyncio
async def test_handoff_artifact_writer_preserves_fallback_without_working_memory(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-artifact-no-memory"
    incident_id = "incident-handoff-artifact-no-memory"
    await _run_chain_to_evidence(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    artifact_context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )
    assert artifact_context.latest_incident_working_memory() is None

    handoff_context = IncidentHandoffContextAssembler().assemble(artifact_context)
    writer = IncidentHandoffArtifactWriter(root=tmp_path / "handoffs")
    path = writer.write(
        artifact_context=artifact_context,
        handoff_context=handoff_context,
    )
    artifact = JsonIncidentHandoffArtifactStore(path).load()

    assert artifact.handoff.current_phase == "evidence_reading_completed"
    assert artifact.handoff.leading_hypothesis_summary is None
    assert artifact.handoff.recommendation_summary is None
    assert all(
        reference.source is not HandoffArtifactSource.INCIDENT_WORKING_MEMORY
        for reference in artifact.handoff.derived_from
    )


@pytest.mark.asyncio
async def test_handoff_artifact_writer_prefers_newer_verified_artifacts_over_stale_memory(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-artifact-stale-memory"
    incident_id = "incident-handoff-artifact-stale-memory"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    artifact_context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )
    working_memory = artifact_context.latest_incident_working_memory()
    assert working_memory is not None
    assert working_memory.source_phase == "recommendation_supported"

    handoff_context = IncidentHandoffContextAssembler().assemble(artifact_context)
    writer = IncidentHandoffArtifactWriter(root=tmp_path / "handoffs")
    path = writer.write(
        artifact_context=artifact_context,
        handoff_context=handoff_context,
    )
    artifact = JsonIncidentHandoffArtifactStore(path).load()

    assert artifact.handoff.current_phase == "action_stub_pending_approval"
    assert artifact.handoff.approval.status is ApprovalStatus.PENDING
    assert artifact.handoff.compact_handoff_note != working_memory.compact_handoff_note
    assert any(
        reference.artifact_name == "incident_action_stub_output"
        for reference in artifact.handoff.derived_from
    )
