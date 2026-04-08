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
    VerifierRequestEvent,
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
    assert result.consulted_artifacts.prior_transcript_event_count == 23

    assert isinstance(events[23], ResumeStartedEvent)
    assert isinstance(events[24], ModelStepEvent)
    assert isinstance(events[25], PermissionDecisionEvent)
    assert isinstance(events[26], ToolRequestEvent)
    assert isinstance(events[27], ToolResultEvent)
    assert isinstance(events[28], VerifierRequestEvent)
    assert isinstance(events[29], VerifierResultEvent)
    assert isinstance(events[30], CheckpointWrittenEvent)

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
async def test_incident_hypothesis_step_rejects_wrong_step_entry_before_any_new_write(
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
    with pytest.raises(ValueError, match="incident_hypothesis step entry"):
        await hypothesis_step.run(
            IncidentHypothesisStepRequest(session_id="session-missing-evidence")
        )

    events = JsonlTranscriptStore(
        tmp_path / "transcripts" / "session-missing-evidence.jsonl"
    ).read_all()
    checkpoint = JsonCheckpointStore(
        tmp_path / "checkpoints" / "session-missing-evidence.json"
    ).load()

    assert len(events) == 15
    assert checkpoint.current_phase == "follow_up_investigation_selected"
    assert checkpoint.pending_verifier is None
