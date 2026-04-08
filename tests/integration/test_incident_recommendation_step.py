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
from agent.state import AgentStatus
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import JsonCheckpointStore
from runtime.models import SyntheticFailureCode
from tools.implementations.incident_recommendation import IncidentRecommendationBuilderTool
from tools.models import ToolCall, ToolResult
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
    assert result.consulted_artifacts.prior_transcript_event_count == 31

    assert isinstance(events[31], ResumeStartedEvent)
    assert isinstance(events[32], ModelStepEvent)
    assert isinstance(events[33], PermissionDecisionEvent)
    assert isinstance(events[34], ToolRequestEvent)
    assert isinstance(events[35], ToolResultEvent)
    assert isinstance(events[36], VerifierRequestEvent)
    assert isinstance(events[37], VerifierResultEvent)
    assert isinstance(events[38], CheckpointWrittenEvent)

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
async def test_incident_recommendation_step_rejects_wrong_step_entry_before_any_new_write(
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
    with pytest.raises(ValueError, match="incident_recommendation step entry"):
        await recommendation_step.run(
            IncidentRecommendationStepRequest(session_id="session-missing-hypothesis")
        )

    events = JsonlTranscriptStore(
        tmp_path / "transcripts" / "session-missing-hypothesis.jsonl"
    ).read_all()
    checkpoint = JsonCheckpointStore(
        tmp_path / "checkpoints" / "session-missing-hypothesis.json"
    ).load()

    assert len(events) == 23
    assert checkpoint.current_phase == "evidence_reading_completed"
    assert checkpoint.pending_verifier is None


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
async def test_incident_recommendation_step_normalizes_malformed_tool_output(
    tmp_path: Path,
) -> None:
    await _run_chain_to_hypothesis(
        tmp_path,
        session_id="session-malformed-recommendation",
        incident_id="incident-malformed-recommendation",
    )

    recommendation_step = IncidentRecommendationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
        tool=_MalformedRecommendationTool(),
    )
    result = await recommendation_step.run(
        IncidentRecommendationStepRequest(session_id="session-malformed-recommendation")
    )

    events = JsonlTranscriptStore(result.consulted_artifacts.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()
    context = SessionArtifactContext.load(
        "session-malformed-recommendation",
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )

    tool_event = events[35]
    assert isinstance(tool_event, ToolResultEvent)
    assert result.recommendation_output is None
    assert result.artifact_failure is not None
    assert result.artifact_failure.code is SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED
    assert result.runner_status is AgentStatus.FAILED
    assert result.verifier_result.status is VerifierStatus.UNVERIFIED
    assert tool_event.result.failure is not None
    assert tool_event.result.failure.synthetic_failure is not None
    assert (
        tool_event.result.failure.synthetic_failure.code
        is SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED
    )
    assert checkpoint.current_phase == "recommendation_failed_artifacts"
    assert checkpoint.pending_verifier is not None

    resolution = context.latest_verified_recommendation_output()
    assert resolution.artifact is None
    assert resolution.failure is not None
    assert resolution.failure.code is SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED
