import json
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
from context.session_artifacts import SessionArtifactContext
from runtime.models import SyntheticFailureCode
from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.implementations.incident_action_stub import ActionCandidateType
from tools.implementations.incident_hypothesis import HypothesisType
from tools.implementations.incident_recommendation import RecommendationType
from verifiers.implementations.incident_action_stub import ActionStubBranch


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


async def _run_chain_to_recommendation(
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
) -> None:
    await _run_chain_to_recommendation(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    action_stub_step = IncidentActionStubStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await action_stub_step.run(IncidentActionStubStepRequest(session_id=session_id))


@pytest.mark.asyncio
async def test_session_artifact_context_loads_latest_verified_chain_outputs(
    tmp_path: Path,
) -> None:
    await _run_chain_to_action_stub(
        tmp_path,
        session_id="session-artifact-context",
        incident_id="incident-artifact-context",
    )

    context = SessionArtifactContext.load(
        "session-artifact-context",
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )

    triage = context.latest_verified_triage_output()
    follow_up = context.latest_verified_follow_up_output()
    follow_up_target = context.latest_verified_follow_up_target()
    evidence = context.latest_verified_evidence_output()
    hypothesis = context.latest_verified_hypothesis_output()
    recommendation = context.latest_verified_recommendation_output()
    action_stub = context.latest_verified_action_stub_output()

    assert context.phase_is("action_stub_pending_approval") is True
    assert triage.artifact is not None
    assert triage.artifact.incident_id == "incident-artifact-context"
    assert follow_up.artifact is not None
    assert follow_up_target.artifact is InvestigationTarget.RECENT_DEPLOYMENT
    assert context.latest_follow_up_target() is InvestigationTarget.RECENT_DEPLOYMENT
    assert evidence.artifact is not None
    assert evidence.artifact.snapshot_id == "deployment-record-2026-04-01"
    assert hypothesis.artifact is not None
    assert hypothesis.artifact.hypothesis_type is HypothesisType.DEPLOYMENT_REGRESSION
    assert recommendation.artifact is not None
    assert (
        recommendation.artifact.recommendation_type
        is RecommendationType.VALIDATE_RECENT_DEPLOYMENT
    )
    assert action_stub.artifact is not None
    assert (
        action_stub.artifact.action_candidate_type
        is ActionCandidateType.DEPLOYMENT_VALIDATION_CANDIDATE
    )


@pytest.mark.asyncio
async def test_session_artifact_context_reports_missing_recommendation_verifier_result(
    tmp_path: Path,
) -> None:
    await _run_chain_to_recommendation(
        tmp_path,
        session_id="session-missing-recommendation-verifier",
        incident_id="incident-missing-recommendation-verifier",
    )

    transcript_path = tmp_path / "transcripts" / "session-missing-recommendation-verifier.jsonl"
    rewritten_lines: list[str] = []
    for raw_line in transcript_path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(raw_line)
        if (
            payload.get("event_type") == "verifier_result"
            and payload.get("verifier_name") == "incident_recommendation_outcome"
        ):
            continue
        rewritten_lines.append(raw_line)
    transcript_path.write_text("\n".join(rewritten_lines) + "\n", encoding="utf-8")

    context = SessionArtifactContext.load(
        "session-missing-recommendation-verifier",
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )
    resolution = context.latest_verified_recommendation_output()

    assert resolution.artifact is None
    assert resolution.failure is not None
    assert resolution.failure.code is SyntheticFailureCode.VERIFIER_RESULT_MISSING
    assert resolution.failure.details["current_phase"] == "recommendation_supported"
    assert resolution.reason is not None


@pytest.mark.asyncio
async def test_action_stub_step_uses_context_for_missing_recommendation_artifact(
    tmp_path: Path,
) -> None:
    await _run_chain_to_recommendation(
        tmp_path,
        session_id="session-step-context-missing-recommendation",
        incident_id="incident-step-context-missing-recommendation",
    )

    transcript_path = (
        tmp_path / "transcripts" / "session-step-context-missing-recommendation.jsonl"
    )
    rewritten_lines: list[str] = []
    for raw_line in transcript_path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(raw_line)
        if (
            payload.get("event_type") == "tool_result"
            and payload.get("tool_name") == "incident_recommendation_builder"
        ):
            continue
        rewritten_lines.append(raw_line)
    transcript_path.write_text("\n".join(rewritten_lines) + "\n", encoding="utf-8")

    action_stub_step = IncidentActionStubStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    result = await action_stub_step.run(
        IncidentActionStubStepRequest(
            session_id="session-step-context-missing-recommendation"
        )
    )

    assert result.resumed_successfully is False
    assert result.branch is ActionStubBranch.INSUFFICIENT_STATE
    assert result.consumed_recommendation_output is None
    assert result.artifact_failure is not None
    assert result.artifact_failure.code is SyntheticFailureCode.REQUIRED_ARTIFACT_UNUSABLE
    assert (
        result.insufficiency_reason
        == "Recommendation artifacts indicate a verified recommendation record should "
        "exist, but the transcript is missing it."
    )
