from pathlib import Path

import pytest

from agent.incident_triage import IncidentTriageStep, IncidentTriageStepRequest
from agent.state import AgentStatus
from memory.checkpoints import JsonCheckpointStore
from transcripts.models import (
    CheckpointWrittenEvent,
    ModelStepEvent,
    PermissionDecisionEvent,
    ToolRequestEvent,
    ToolResultEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierStatus


@pytest.mark.asyncio
async def test_incident_triage_step_runs_end_to_end_and_persists_artifacts(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    step = IncidentTriageStep(
        skills_root=repository_root / "skills",
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )

    result = await step.run(
        IncidentTriageStepRequest(
            session_id="session-100",
            incident_id="incident-100",
            title="Elevated 5xx errors on payments-api",
            service="payments-api",
            symptoms=["spike in 5xx", "checkout requests timing out"],
            impact_summary="Customer checkout requests are failing intermittently.",
        )
    )

    events = JsonlTranscriptStore(result.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.completed is True
    assert result.status is AgentStatus.COMPLETED
    assert result.triage_output is not None
    assert result.verifier_result.status is VerifierStatus.PASS
    assert result.permission_decision.tool_name == "incident_payload_summary"

    assert isinstance(events[0], ModelStepEvent)
    assert isinstance(events[1], PermissionDecisionEvent)
    assert isinstance(events[2], ToolRequestEvent)
    assert isinstance(events[3], ToolResultEvent)
    assert isinstance(events[4], VerifierResultEvent)
    assert isinstance(events[5], CheckpointWrittenEvent)

    assert checkpoint.session_id == "session-100"
    assert checkpoint.incident_id == "incident-100"
    assert checkpoint.current_phase == "triage_completed"
    assert checkpoint.selected_skills == ["incident-triage"]
    assert checkpoint.pending_verifier is None
