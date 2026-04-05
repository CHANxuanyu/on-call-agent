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
async def test_handoff_context_uses_current_working_memory_when_available(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-recommendation"
    incident_id = "incident-handoff-recommendation"
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
    working_memory = artifact_context.latest_incident_working_memory()
    assert working_memory is not None

    handoff = IncidentHandoffContextAssembler().assemble(artifact_context)

    assert handoff.incident_id == incident_id
    assert handoff.service == "payments-api"
    assert handoff.current_phase == "recommendation_supported"
    assert "recommendation" in handoff.progress_summary.lower()
    assert handoff.leading_hypothesis_summary is not None
    assert "deployment regression" in handoff.leading_hypothesis_summary.lower()
    assert handoff.recommendation_summary is not None
    assert "validate rollback readiness" in handoff.recommendation_summary.lower()
    assert handoff.approval.status is ApprovalStatus.NONE
    assert handoff.current_operator_attention_point == handoff.recommendation_summary
    assert handoff.compact_handoff_note == working_memory.compact_handoff_note
    assert any(
        reference.source is HandoffArtifactSource.INCIDENT_WORKING_MEMORY
        for reference in handoff.derived_from
    )


@pytest.mark.asyncio
async def test_handoff_context_falls_back_without_working_memory_and_is_read_only(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-no-working-memory"
    incident_id = "incident-handoff-no-working-memory"
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
    checkpoint_before = artifact_context.checkpoint_path.read_text(encoding="utf-8")
    transcript_before = artifact_context.transcript_path.read_text(encoding="utf-8")
    assert not artifact_context.working_memory_path.exists()

    handoff = IncidentHandoffContextAssembler().assemble(artifact_context)

    assert handoff.current_phase == "evidence_reading_completed"
    assert handoff.leading_hypothesis_summary is None
    assert handoff.recommendation_summary is None
    assert "deployment diff" in handoff.current_operator_attention_point.lower()
    assert "Current phase is evidence_reading_completed." in handoff.compact_handoff_note
    assert not artifact_context.working_memory_path.exists()
    assert artifact_context.checkpoint_path.read_text(encoding="utf-8") == checkpoint_before
    assert artifact_context.transcript_path.read_text(encoding="utf-8") == transcript_before
    assert all(
        reference.source is not HandoffArtifactSource.INCIDENT_WORKING_MEMORY
        for reference in handoff.derived_from
    )


@pytest.mark.asyncio
async def test_handoff_context_uses_verified_artifacts_when_working_memory_is_absent(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-artifact-fallback"
    incident_id = "incident-handoff-artifact-fallback"
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
    assert artifact_context.working_memory_path.exists()
    artifact_context.working_memory_path.unlink()

    reloaded_context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )
    handoff = IncidentHandoffContextAssembler().assemble(reloaded_context)

    assert handoff.current_phase == "recommendation_supported"
    assert handoff.leading_hypothesis_summary is not None
    assert handoff.recommendation_summary is not None
    assert "validate rollback readiness" in handoff.recommendation_summary.lower()
    assert handoff.compact_handoff_note != ""
    assert all(
        reference.source is not HandoffArtifactSource.INCIDENT_WORKING_MEMORY
        for reference in handoff.derived_from
    )


@pytest.mark.asyncio
async def test_handoff_context_prefers_newer_verified_artifacts_over_stale_working_memory(
    tmp_path: Path,
) -> None:
    session_id = "session-handoff-stale-working-memory"
    incident_id = "incident-handoff-stale-working-memory"
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
    assert artifact_context.checkpoint.current_phase == "action_stub_pending_approval"

    handoff = IncidentHandoffContextAssembler().assemble(artifact_context)

    assert handoff.current_phase == "action_stub_pending_approval"
    assert handoff.approval.status is ApprovalStatus.PENDING
    assert handoff.approval.requested_action == "rollback_recent_deployment_candidate"
    assert "review the approval gate" in handoff.current_operator_attention_point.lower()
    assert handoff.compact_handoff_note != working_memory.compact_handoff_note
    assert "Pending approval" in (handoff.approval.summary or "")
    assert any(
        reference.artifact_name == "incident_action_stub_output"
        for reference in handoff.derived_from
    )
