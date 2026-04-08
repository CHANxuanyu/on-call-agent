from pathlib import Path

import pytest

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
from verifiers.implementations.follow_up_investigation import FollowUpBranch


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_incident_follow_up_step_no_ops_when_verified_triage_has_no_unknowns(
    tmp_path: Path,
) -> None:
    triage_step = IncidentTriageStep(
        skills_root=_repository_root() / "skills",
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await triage_step.run(
        IncidentTriageStepRequest(
            session_id="session-noop",
            incident_id="incident-noop",
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
    result = await follow_up_step.run(
        IncidentFollowUpStepRequest(session_id="session-noop")
    )

    events = JsonlTranscriptStore(result.consulted_artifacts.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is True
    assert result.branch is FollowUpBranch.NO_OP
    assert result.runner_status is AgentStatus.COMPLETED
    assert result.more_follow_up_required is False
    assert result.triage_was_verified_complete is True
    assert result.no_op_reason is not None
    assert result.consulted_artifacts.previous_phase == "triage_completed"
    assert result.consulted_artifacts.prior_transcript_event_count == 7
    assert result.verifier_result.status is VerifierStatus.PASS

    assert isinstance(events[7], ResumeStartedEvent)
    assert isinstance(events[8], ModelStepEvent)
    assert isinstance(events[9], VerifierRequestEvent)
    assert isinstance(events[10], VerifierResultEvent)
    assert isinstance(events[11], CheckpointWrittenEvent)

    assert checkpoint.current_phase == "follow_up_complete_no_action"
    assert checkpoint.pending_verifier is None


@pytest.mark.asyncio
async def test_incident_follow_up_step_investigates_when_unknowns_remain(
    tmp_path: Path,
) -> None:
    triage_step = IncidentTriageStep(
        skills_root=_repository_root() / "skills",
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await triage_step.run(
        IncidentTriageStepRequest(
            session_id="session-investigate",
            incident_id="incident-investigate",
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
    result = await follow_up_step.run(
        IncidentFollowUpStepRequest(session_id="session-investigate")
    )

    events = JsonlTranscriptStore(result.consulted_artifacts.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is True
    assert result.branch is FollowUpBranch.INVESTIGATE
    assert result.runner_status is AgentStatus.RUNNING
    assert result.more_follow_up_required is True
    assert result.permission_decision is not None
    assert result.investigation_output is not None
    assert result.verifier_result.status is VerifierStatus.PASS
    assert result.consulted_artifacts.prior_transcript_event_count == 7

    assert isinstance(events[7], ResumeStartedEvent)
    assert isinstance(events[8], ModelStepEvent)
    assert isinstance(events[9], PermissionDecisionEvent)
    assert isinstance(events[10], ToolRequestEvent)
    assert isinstance(events[11], ToolResultEvent)
    assert isinstance(events[12], VerifierRequestEvent)
    assert isinstance(events[13], VerifierResultEvent)
    assert isinstance(events[14], CheckpointWrittenEvent)

    assert checkpoint.current_phase == "follow_up_investigation_selected"
    assert checkpoint.pending_verifier is None
