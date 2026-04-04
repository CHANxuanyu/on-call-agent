from pathlib import Path
from typing import cast

import pytest

from agent.incident_evidence import IncidentEvidenceStep, IncidentEvidenceStepRequest
from agent.incident_follow_up import IncidentFollowUpStep, IncidentFollowUpStepRequest
from agent.incident_hypothesis import IncidentHypothesisStep, IncidentHypothesisStepRequest
from agent.incident_recommendation import (
    IncidentRecommendationStep,
    IncidentRecommendationStepRequest,
)
from agent.incident_triage import IncidentTriageStep, IncidentTriageStepRequest
from context.session_artifacts import SessionArtifactContext
from memory.incident_working_memory import JsonIncidentWorkingMemoryStore
from tools.implementations.incident_hypothesis import HypothesisType
from tools.implementations.incident_recommendation import (
    IncidentRecommendationBuilderTool,
    RecommendationType,
)
from tools.models import ToolCall, ToolResult


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


class _MalformedRecommendationTool(IncidentRecommendationBuilderTool):
    async def execute(self, call: ToolCall) -> ToolResult:
        del call
        return cast(
            ToolResult,
            {
                "status": "succeeded",
                "output": {"unexpected": "shape"},
            },
        )


@pytest.mark.asyncio
async def test_hypothesis_step_writes_first_incident_working_memory_snapshot(
    tmp_path: Path,
) -> None:
    await _run_chain_to_evidence(
        tmp_path,
        session_id="session-working-memory-hypothesis",
        incident_id="incident-working-memory-hypothesis",
    )

    hypothesis_step = IncidentHypothesisStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await hypothesis_step.run(
        IncidentHypothesisStepRequest(session_id="session-working-memory-hypothesis")
    )

    store = JsonIncidentWorkingMemoryStore.for_incident(
        "incident-working-memory-hypothesis",
        root=tmp_path / "working_memory",
    )
    memory = store.load()
    context = SessionArtifactContext.load(
        "session-working-memory-hypothesis",
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )

    assert memory.last_updated_by_step == "incident_hypothesis"
    assert memory.source_phase == "hypothesis_supported"
    assert memory.leading_hypothesis is not None
    assert memory.leading_hypothesis.hypothesis_type is HypothesisType.DEPLOYMENT_REGRESSION
    assert memory.recommendation is None
    assert "No verified recommendation has been recorded yet." in memory.compact_handoff_note
    assert context.latest_incident_working_memory() == memory
    assert context.working_memory_path == store.path


@pytest.mark.asyncio
async def test_recommendation_step_updates_incident_working_memory_snapshot(
    tmp_path: Path,
) -> None:
    await _run_chain_to_hypothesis(
        tmp_path,
        session_id="session-working-memory-recommendation",
        incident_id="incident-working-memory-recommendation",
    )

    recommendation_step = IncidentRecommendationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await recommendation_step.run(
        IncidentRecommendationStepRequest(
            session_id="session-working-memory-recommendation"
        )
    )

    store = JsonIncidentWorkingMemoryStore.for_incident(
        "incident-working-memory-recommendation",
        root=tmp_path / "working_memory",
    )
    memory = store.load()
    context = SessionArtifactContext.load(
        "session-working-memory-recommendation",
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )

    assert memory.last_updated_by_step == "incident_recommendation"
    assert memory.source_phase == "recommendation_supported"
    assert memory.leading_hypothesis is not None
    assert memory.recommendation is not None
    assert (
        memory.recommendation.recommendation_type
        is RecommendationType.VALIDATE_RECENT_DEPLOYMENT
    )
    assert "Current recommendation is validate_recent_deployment." in memory.compact_handoff_note
    assert context.latest_incident_working_memory() == memory


@pytest.mark.asyncio
async def test_failed_recommendation_does_not_overwrite_working_memory(
    tmp_path: Path,
) -> None:
    await _run_chain_to_hypothesis(
        tmp_path,
        session_id="session-working-memory-failed-recommendation",
        incident_id="incident-working-memory-failed-recommendation",
    )

    store = JsonIncidentWorkingMemoryStore.for_incident(
        "incident-working-memory-failed-recommendation",
        root=tmp_path / "working_memory",
    )
    hypothesis_memory = store.load()

    recommendation_step = IncidentRecommendationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
        tool=_MalformedRecommendationTool(),
    )
    await recommendation_step.run(
        IncidentRecommendationStepRequest(
            session_id="session-working-memory-failed-recommendation"
        )
    )

    memory_after_failure = store.load()

    assert memory_after_failure == hypothesis_memory
    assert memory_after_failure.last_updated_by_step == "incident_hypothesis"
