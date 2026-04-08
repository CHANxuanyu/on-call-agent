from pathlib import Path

import pytest

from agent.incident_evidence import IncidentEvidenceStep, IncidentEvidenceStepRequest
from agent.incident_follow_up import IncidentFollowUpStep, IncidentFollowUpStepRequest
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
from verifiers.implementations.evidence_reading import EvidenceReadBranch


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_incident_evidence_step_reads_evidence_for_selected_target(
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
            session_id="session-evidence",
            incident_id="incident-evidence",
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
        IncidentFollowUpStepRequest(session_id="session-evidence")
    )

    evidence_step = IncidentEvidenceStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    evidence_step.tool.fixtures_path = repo_root / "evals/fixtures/evidence_snapshots.json"

    result = await evidence_step.run(
        IncidentEvidenceStepRequest(session_id="session-evidence")
    )

    events = JsonlTranscriptStore(result.consulted_artifacts.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is True
    assert result.branch is EvidenceReadBranch.READ_EVIDENCE
    assert result.selected_investigation_target is not None
    assert result.evidence_action_name == "evidence_bundle_reader"
    assert result.runner_status is AgentStatus.RUNNING
    assert result.more_follow_up_required is True
    assert result.verifier_result.status is VerifierStatus.PASS
    assert result.evidence_output is not None
    assert result.evidence_output.snapshot_id == "deployment-record-2026-04-01"
    assert result.consulted_artifacts.previous_phase == "follow_up_investigation_selected"
    assert result.consulted_artifacts.prior_transcript_event_count == 15

    assert isinstance(events[15], ResumeStartedEvent)
    assert isinstance(events[16], ModelStepEvent)
    assert isinstance(events[17], PermissionDecisionEvent)
    assert isinstance(events[18], ToolRequestEvent)
    assert isinstance(events[19], ToolResultEvent)
    assert isinstance(events[20], VerifierRequestEvent)
    assert isinstance(events[21], VerifierResultEvent)
    assert isinstance(events[22], CheckpointWrittenEvent)

    assert checkpoint.current_phase == "evidence_reading_completed"
    assert checkpoint.pending_verifier is None


@pytest.mark.asyncio
async def test_incident_evidence_step_rejects_wrong_step_entry_before_any_new_write(
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
            session_id="session-no-target",
            incident_id="incident-no-target",
            title="Elevated 5xx errors on payments-api",
            service="payments-api",
            symptoms=["spike in 5xx"],
            impact_summary="Customer checkout requests are failing intermittently.",
        )
    )

    evidence_step = IncidentEvidenceStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    evidence_step.tool.fixtures_path = repo_root / "evals/fixtures/evidence_snapshots.json"

    with pytest.raises(ValueError, match="incident_evidence step entry"):
        await evidence_step.run(IncidentEvidenceStepRequest(session_id="session-no-target"))

    events = JsonlTranscriptStore(tmp_path / "transcripts" / "session-no-target.jsonl").read_all()
    checkpoint = JsonCheckpointStore(
        tmp_path / "checkpoints" / "session-no-target.json"
    ).load()

    assert len(events) == 7
    assert checkpoint.current_phase == "triage_completed"
    assert checkpoint.pending_verifier is None


@pytest.mark.asyncio
async def test_incident_evidence_step_preserves_not_applicable_same_family_runtime_result(
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
            session_id="session-no-action-follow-up",
            incident_id="incident-no-action-follow-up",
            title="Elevated 5xx errors on payments-api",
            service="payments-api",
            symptoms=["spike in 5xx"],
            impact_summary="Customer checkout requests are failing intermittently.",
            recent_deployment="deploy-2026-04-01-1",
            runbook_reference="runbook/payments-api",
            ownership_team="payments-oncall",
        )
    )

    follow_up_step = IncidentFollowUpStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await follow_up_step.run(
        IncidentFollowUpStepRequest(session_id="session-no-action-follow-up")
    )

    evidence_step = IncidentEvidenceStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    evidence_step.tool.fixtures_path = repo_root / "evals/fixtures/evidence_snapshots.json"

    result = await evidence_step.run(
        IncidentEvidenceStepRequest(session_id="session-no-action-follow-up")
    )

    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is False
    assert result.branch is EvidenceReadBranch.INSUFFICIENT_STATE
    assert result.insufficiency_reason is not None
    assert result.consulted_artifacts.previous_phase == "follow_up_complete_no_action"
    assert result.verifier_result.status is VerifierStatus.PASS
    assert checkpoint.current_phase == "evidence_reading_not_applicable"
