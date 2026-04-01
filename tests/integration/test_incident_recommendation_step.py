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
from agent.state import AgentStatus
from memory.checkpoints import JsonCheckpointStore
from transcripts.models import (
    CheckpointWrittenEvent,
    ModelStepEvent,
    PermissionDecisionEvent,
    ResumeStartedEvent,
    ToolRequestEvent,
    ToolResultEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierStatus
from verifiers.implementations.incident_recommendation import RecommendationBranch


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


async def _run_chain_to_hypothesis(
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

    hypothesis_step = IncidentHypothesisStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await hypothesis_step.run(IncidentHypothesisStepRequest(session_id=session_id))


@pytest.mark.asyncio
async def test_incident_recommendation_step_builds_supported_recommendation(
    tmp_path: Path,
) -> None:
    await _run_chain_to_hypothesis(
        tmp_path,
        session_id="session-supported-recommendation",
        incident_id="incident-supported-recommendation",
    )

    recommendation_step = IncidentRecommendationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    result = await recommendation_step.run(
        IncidentRecommendationStepRequest(session_id="session-supported-recommendation")
    )

    events = JsonlTranscriptStore(result.consulted_artifacts.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is True
    assert result.branch is RecommendationBranch.BUILD_RECOMMENDATION
    assert result.consumed_hypothesis_output is not None
    assert result.recommendation_action_name == "incident_recommendation_builder"
    assert result.runner_status is AgentStatus.RUNNING
    assert result.hypothesis_supported is True
    assert result.conservative_due_to_insufficient_evidence is False
    assert result.future_action_requires_approval is True
    assert result.more_follow_up_required is True
    assert result.verifier_result.status is VerifierStatus.PASS
    assert result.recommendation_output is not None
    assert result.recommendation_output.recommendation_type == "validate_recent_deployment"
    assert result.consulted_artifacts.previous_phase == "hypothesis_supported"
    assert result.consulted_artifacts.prior_transcript_event_count == 27

    assert isinstance(events[27], ResumeStartedEvent)
    assert isinstance(events[28], ModelStepEvent)
    assert isinstance(events[29], PermissionDecisionEvent)
    assert isinstance(events[30], ToolRequestEvent)
    assert isinstance(events[31], ToolResultEvent)
    assert isinstance(events[32], VerifierResultEvent)
    assert isinstance(events[33], CheckpointWrittenEvent)

    assert checkpoint.current_phase == "recommendation_supported"
    assert checkpoint.pending_verifier is None


@pytest.mark.asyncio
async def test_incident_recommendation_step_builds_conservative_recommendation(
    tmp_path: Path,
) -> None:
    await _run_chain_to_hypothesis(
        tmp_path,
        session_id="session-conservative-recommendation",
        incident_id="incident-conservative-recommendation",
        recent_deployment="deploy-2026-04-01-1",
    )

    recommendation_step = IncidentRecommendationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    result = await recommendation_step.run(
        IncidentRecommendationStepRequest(session_id="session-conservative-recommendation")
    )

    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is True
    assert result.branch is RecommendationBranch.BUILD_RECOMMENDATION
    assert result.hypothesis_supported is False
    assert result.conservative_due_to_insufficient_evidence is True
    assert result.future_action_requires_approval is False
    assert result.recommendation_output is not None
    assert result.recommendation_output.recommendation_type == "investigate_more"
    assert result.verifier_result.status is VerifierStatus.PASS
    assert checkpoint.current_phase == "recommendation_conservative"
    assert checkpoint.pending_verifier is None


@pytest.mark.asyncio
async def test_incident_recommendation_step_records_insufficient_state_without_hypothesis_record(
    tmp_path: Path,
) -> None:
    repo_root = _repository_root()
    triage_step = IncidentTriageStep(
        skills_root=repo_root / "skills",
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await triage_step.run(
        IncidentTriageStepRequest(
            session_id="session-missing-hypothesis",
            incident_id="incident-missing-hypothesis",
            title="Elevated 5xx errors on payments-api",
            service="payments-api",
            symptoms=["spike in 5xx", "checkout requests timing out"],
            impact_summary="Customer checkout requests are failing intermittently.",
        )
    )

    follow_up_step = IncidentFollowUpStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await follow_up_step.run(
        IncidentFollowUpStepRequest(session_id="session-missing-hypothesis")
    )

    evidence_step = IncidentEvidenceStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    evidence_step.tool.fixtures_path = repo_root / "evals/fixtures/evidence_snapshots.json"
    await evidence_step.run(
        IncidentEvidenceStepRequest(session_id="session-missing-hypothesis")
    )

    recommendation_step = IncidentRecommendationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    result = await recommendation_step.run(
        IncidentRecommendationStepRequest(session_id="session-missing-hypothesis")
    )

    events = JsonlTranscriptStore(result.consulted_artifacts.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is False
    assert result.branch is RecommendationBranch.INSUFFICIENT_STATE
    assert result.consumed_hypothesis_output is None
    assert result.runner_status is AgentStatus.VERIFYING
    assert result.conservative_due_to_insufficient_evidence is None
    assert result.future_action_requires_approval is None
    assert result.verifier_result.status is VerifierStatus.PASS
    assert result.insufficiency_reason is not None
    assert result.consulted_artifacts.previous_phase == "evidence_reading_completed"
    assert result.consulted_artifacts.prior_transcript_event_count == 20

    assert isinstance(events[20], ResumeStartedEvent)
    assert isinstance(events[21], ModelStepEvent)
    assert isinstance(events[22], VerifierResultEvent)
    assert isinstance(events[23], CheckpointWrittenEvent)

    assert checkpoint.current_phase == "recommendation_deferred"
    assert checkpoint.pending_verifier is None
