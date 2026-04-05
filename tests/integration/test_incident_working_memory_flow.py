from pathlib import Path
from typing import cast

import pytest

from agent.deployment_outcome_verification import DeploymentOutcomeVerificationStep
from agent.incident_evidence import IncidentEvidenceStep, IncidentEvidenceStepRequest
from agent.incident_follow_up import IncidentFollowUpStep, IncidentFollowUpStepRequest
from agent.incident_hypothesis import IncidentHypothesisStep, IncidentHypothesisStepRequest
from agent.incident_recommendation import (
    IncidentRecommendationStep,
    IncidentRecommendationStepRequest,
)
from agent.incident_triage import IncidentTriageStep, IncidentTriageStepRequest
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import SessionCheckpoint
from memory.incident_working_memory import JsonIncidentWorkingMemoryStore
from tools.implementations.deployment_outcome_probe import DeploymentOutcomeProbeOutput
from tools.implementations.deployment_rollback import DeploymentRollbackExecutionOutput
from tools.implementations.incident_hypothesis import (
    DEPLOYMENT_REGRESSION_VALIDATION_GAP,
    HypothesisType,
)
from tools.implementations.incident_recommendation import (
    IncidentRecommendationBuilderTool,
    RecommendationType,
)
from tools.models import ToolCall, ToolResult
from verifiers.base import VerifierResult, VerifierStatus


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


@pytest.mark.asyncio
async def test_outcome_verification_success_rewrites_working_memory_with_resolved_state(
    tmp_path: Path,
) -> None:
    session_id = "session-working-memory-outcome"
    incident_id = "incident-working-memory-outcome"
    await _run_chain_to_hypothesis(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    recommendation_step = IncidentRecommendationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await recommendation_step.run(
        IncidentRecommendationStepRequest(session_id=session_id)
    )

    store = JsonIncidentWorkingMemoryStore.for_incident(
        incident_id,
        root=tmp_path / "working_memory",
    )
    memory_before = store.load()
    assert DEPLOYMENT_REGRESSION_VALIDATION_GAP in memory_before.unresolved_gaps

    artifact_context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )
    outcome_step = DeploymentOutcomeVerificationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    outcome_step._write_incident_working_memory(
        session_id=session_id,
        checkpoint=SessionCheckpoint(
            checkpoint_id=f"{session_id}-deployment-outcome-verification",
            session_id=session_id,
            incident_id=incident_id,
            current_phase="outcome_verification_succeeded",
            current_step=artifact_context.checkpoint.current_step + 1,
            selected_skills=artifact_context.checkpoint.selected_skills,
            approval_state=artifact_context.checkpoint.approval_state,
            summary_of_progress="Outcome verification passed.",
        ),
        verifier_result=VerifierResult(
            status=VerifierStatus.PASS,
            summary="Recovery verified after rollback.",
        ),
        artifact_context=artifact_context,
        action_execution_output=DeploymentRollbackExecutionOutput(
            incident_id=incident_id,
            service="payments-api",
            service_base_url="http://127.0.0.1:8001",
            action_candidate_type="rollback_recent_deployment_candidate",
            rollback_applied=True,
            observed_version_before="2.1.0",
            observed_version_after="2.0.9",
            expected_bad_version="2.1.0",
            expected_previous_version="2.0.9",
            health_status_before="degraded",
            health_status_after="healthy",
            execution_summary="Rolled payments-api back from 2.1.0 to 2.0.9.",
            safety_notes=["Rollback stayed within the reviewed scope."],
        ),
        outcome_probe_output=DeploymentOutcomeProbeOutput(
            incident_id=incident_id,
            service="payments-api",
            service_base_url="http://127.0.0.1:8001",
            current_version="2.0.9",
            expected_previous_version="2.0.9",
            health_status="healthy",
            healthy=True,
            error_rate=0.01,
            timeout_rate=0.0,
            latency_p95_ms=120,
            evidence_refs=[
                "http://127.0.0.1:8001/deployment",
                "http://127.0.0.1:8001/health",
                "http://127.0.0.1:8001/metrics",
            ],
            summary=(
                "Runtime probe sees version 2.0.9, health_status=healthy, "
                "error_rate=0.01, timeout_rate=0.00."
            ),
        ),
    )

    memory_after_success = store.load()

    assert memory_after_success.source_phase == "outcome_verification_succeeded"
    assert (
        memory_after_success.last_updated_by_step
        == "deployment_outcome_verification"
    )
    assert memory_after_success.unresolved_gaps == []
    assert "rollback:2.1.0->2.0.9" in memory_after_success.important_evidence_references
    assert "http://127.0.0.1:8001/metrics" in memory_after_success.important_evidence_references
    assert memory_after_success.recommendation is not None
    assert memory_after_success.recommendation.more_investigation_required is False
    assert "Outcome verification passed" in memory_after_success.compact_handoff_note
