from pathlib import Path

import pytest

from agent.incident_evidence import IncidentEvidenceStep, IncidentEvidenceStepRequest
from agent.incident_follow_up import IncidentFollowUpStep, IncidentFollowUpStepRequest
from agent.incident_hypothesis import IncidentHypothesisStep, IncidentHypothesisStepRequest
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
from verifiers.implementations.incident_hypothesis import HypothesisBranch


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


@pytest.mark.asyncio
async def test_incident_hypothesis_step_builds_supported_deployment_regression(
    tmp_path: Path,
) -> None:
    await _run_chain_to_evidence(
        tmp_path,
        session_id="session-supported-hypothesis",
        incident_id="incident-supported-hypothesis",
    )

    hypothesis_step = IncidentHypothesisStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    result = await hypothesis_step.run(
        IncidentHypothesisStepRequest(session_id="session-supported-hypothesis")
    )

    events = JsonlTranscriptStore(result.consulted_artifacts.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is True
    assert result.branch is HypothesisBranch.BUILD_HYPOTHESIS
    assert result.consumed_evidence_output is not None
    assert result.hypothesis_action_name == "incident_hypothesis_builder"
    assert result.runner_status is AgentStatus.RUNNING
    assert result.evidence_supported is True
    assert result.more_follow_up_required is True
    assert result.verifier_result.status is VerifierStatus.PASS
    assert result.hypothesis_output is not None
    assert result.hypothesis_output.hypothesis_type == "deployment_regression"
    assert result.consulted_artifacts.previous_phase == "evidence_reading_completed"
    assert result.consulted_artifacts.prior_transcript_event_count == 20

    assert isinstance(events[20], ResumeStartedEvent)
    assert isinstance(events[21], ModelStepEvent)
    assert isinstance(events[22], PermissionDecisionEvent)
    assert isinstance(events[23], ToolRequestEvent)
    assert isinstance(events[24], ToolResultEvent)
    assert isinstance(events[25], VerifierResultEvent)
    assert isinstance(events[26], CheckpointWrittenEvent)

    assert checkpoint.current_phase == "hypothesis_supported"
    assert checkpoint.pending_verifier is None


@pytest.mark.asyncio
async def test_incident_hypothesis_step_builds_insufficient_evidence_result(
    tmp_path: Path,
) -> None:
    await _run_chain_to_evidence(
        tmp_path,
        session_id="session-insufficient-hypothesis",
        incident_id="incident-insufficient-hypothesis",
        recent_deployment="deploy-2026-04-01-1",
    )

    hypothesis_step = IncidentHypothesisStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    result = await hypothesis_step.run(
        IncidentHypothesisStepRequest(session_id="session-insufficient-hypothesis")
    )

    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is True
    assert result.branch is HypothesisBranch.BUILD_HYPOTHESIS
    assert result.evidence_supported is False
    assert result.hypothesis_output is not None
    assert result.hypothesis_output.hypothesis_type == "insufficient_evidence"
    assert result.verifier_result.status is VerifierStatus.PASS
    assert checkpoint.current_phase == "hypothesis_insufficient_evidence"
    assert checkpoint.pending_verifier is None


@pytest.mark.asyncio
async def test_incident_hypothesis_step_records_insufficient_state_without_evidence_record(
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
            session_id="session-missing-evidence",
            incident_id="incident-missing-evidence",
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
        IncidentFollowUpStepRequest(session_id="session-missing-evidence")
    )

    hypothesis_step = IncidentHypothesisStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    result = await hypothesis_step.run(
        IncidentHypothesisStepRequest(session_id="session-missing-evidence")
    )

    events = JsonlTranscriptStore(result.consulted_artifacts.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is False
    assert result.branch is HypothesisBranch.INSUFFICIENT_STATE
    assert result.consumed_evidence_output is None
    assert result.runner_status is AgentStatus.VERIFYING
    assert result.evidence_supported is None
    assert result.verifier_result.status is VerifierStatus.PASS
    assert result.insufficiency_reason is not None
    assert result.consulted_artifacts.previous_phase == "follow_up_investigation_selected"
    assert result.consulted_artifacts.prior_transcript_event_count == 13

    assert isinstance(events[13], ResumeStartedEvent)
    assert isinstance(events[14], ModelStepEvent)
    assert isinstance(events[15], VerifierResultEvent)
    assert isinstance(events[16], CheckpointWrittenEvent)

    assert checkpoint.current_phase == "hypothesis_deferred"
    assert checkpoint.pending_verifier is None
