import socket
from pathlib import Path

import httpx
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
from runtime.console_server import OperatorConsoleServer


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _can_bind_local_socket() -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
    except OSError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _can_bind_local_socket(),
    reason="local TCP bind is unavailable in the current sandbox",
)


async def _run_chain_to_action_stub(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
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
            recent_deployment="deployment-2026-04-01",
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

    recommendation_step = IncidentRecommendationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await recommendation_step.run(IncidentRecommendationStepRequest(session_id=session_id))

    action_stub_step = IncidentActionStubStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await action_stub_step.run(IncidentActionStubStepRequest(session_id=session_id))


@pytest.mark.asyncio
async def test_console_server_serves_panel_first_page_and_assistant_route(
    tmp_path: Path,
) -> None:
    session_id = "session-console-server"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id="incident-console-server",
    )

    with OperatorConsoleServer(
        host="127.0.0.1",
        port=0,
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    ) as server:
        with httpx.Client(base_url=server.base_url, timeout=5.0) as client:
            root_response = client.get("/")
            assert root_response.status_code == 200
            assert "Session Assistant" in root_response.text
            assert "Incident Detail" in root_response.text

            sessions_response = client.get("/api/phase1/sessions?limit=10")
            assert sessions_response.status_code == 200
            sessions_payload = sessions_response.json()
            assert sessions_payload["sessions"][0]["session_id"] == session_id

            assistant_response = client.post(
                f"/api/phase1/sessions/{session_id}/assistant",
                json={"prompt": "Why is this session blocked?"},
            )
            assert assistant_response.status_code == 200
            assistant_payload = assistant_response.json()
            assert assistant_payload["session_id"] == session_id
            assert assistant_payload["intent"] == "blocked_or_ready"
            assert "blocked on explicit human approval" in assistant_payload["answer"]
            assert assistant_payload["grounding"]["chat_history_persisted"] is False
            assert "authority_sources" in assistant_payload["grounding"]
            assert "supporting_sources" in assistant_payload["grounding"]
