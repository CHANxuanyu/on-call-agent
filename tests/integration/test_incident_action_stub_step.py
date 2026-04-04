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
from agent.state import AgentStatus
from memory.checkpoints import ApprovalStatus, JsonCheckpointStore
from permissions.models import (
    EvaluatedActionType,
    PermissionActionCategory,
    PermissionPolicySource,
    PermissionSafetyBoundary,
)
from tools.implementations.incident_action_stub import ActionCandidateType
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


@pytest.mark.asyncio
async def test_incident_action_stub_step_builds_approval_gated_candidate(
    tmp_path: Path,
) -> None:
    await _run_chain_to_recommendation(
        tmp_path,
        session_id="session-action-stub-supported",
        incident_id="incident-action-stub-supported",
    )

    action_stub_step = IncidentActionStubStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    result = await action_stub_step.run(
        IncidentActionStubStepRequest(session_id="session-action-stub-supported")
    )

    events = JsonlTranscriptStore(result.consulted_artifacts.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is True
    assert result.branch is ActionStubBranch.BUILD_ACTION_STUB
    assert result.consumed_recommendation_output is not None
    assert result.action_stub_action_name == "incident_action_stub_builder"
    assert result.action_candidate_produced is True
    assert result.approval_required is True
    assert result.runner_status is AgentStatus.WAITING_FOR_APPROVAL
    assert result.recommendation_supported is True
    assert result.conservative_due_to_insufficient_evidence is False
    assert result.future_non_read_only_action_blocked_pending_approval is True
    assert result.verifier_result.status is VerifierStatus.PASS
    assert result.action_stub_output is not None
    assert result.permission_decision is not None
    assert (
        result.action_stub_output.action_candidate_type
        is ActionCandidateType.DEPLOYMENT_VALIDATION_CANDIDATE
    )
    assert (
        result.permission_decision.provenance.policy_source
        is PermissionPolicySource.DEFAULT_SAFE_TOOL_RISK
    )
    assert (
        result.permission_decision.provenance.action_category
        is PermissionActionCategory.TOOL_EXECUTION
    )
    assert (
        result.permission_decision.provenance.evaluated_action_type
        is EvaluatedActionType.READ_ONLY_TOOL
    )
    assert result.permission_decision.provenance.approval_required is False
    assert (
        result.permission_decision.provenance.safety_boundary
        is PermissionSafetyBoundary.READ_ONLY_ONLY
    )
    assert result.consulted_artifacts.previous_phase == "recommendation_supported"
    assert result.consulted_artifacts.prior_transcript_event_count == 34

    assert isinstance(events[34], ResumeStartedEvent)
    assert isinstance(events[35], ModelStepEvent)
    assert isinstance(events[36], PermissionDecisionEvent)
    assert isinstance(events[37], ToolRequestEvent)
    assert isinstance(events[38], ToolResultEvent)
    assert isinstance(events[39], VerifierResultEvent)
    assert isinstance(events[40], CheckpointWrittenEvent)

    assert checkpoint.current_phase == "action_stub_pending_approval"
    assert checkpoint.approval_state.status is ApprovalStatus.PENDING
    permission_event = events[36]
    assert isinstance(permission_event, PermissionDecisionEvent)
    assert (
        permission_event.decision.provenance.policy_source
        is PermissionPolicySource.DEFAULT_SAFE_TOOL_RISK
    )
    assert (
        permission_event.decision.provenance.evaluated_action_type
        is EvaluatedActionType.READ_ONLY_TOOL
    )
    assert checkpoint.approval_state.future_preconditions == [
        "Confirm the deployment diff matches the affected request path.",
        "Keep all next actions advisory until on-call lead approval is recorded.",
        "Human approval must be recorded before any non-read-only action.",
    ]
    assert checkpoint.pending_verifier is None


@pytest.mark.asyncio
async def test_incident_action_stub_step_builds_no_actionable_outcome(
    tmp_path: Path,
) -> None:
    await _run_chain_to_recommendation(
        tmp_path,
        session_id="session-action-stub-conservative",
        incident_id="incident-action-stub-conservative",
        recent_deployment="deploy-2026-04-01-1",
    )

    action_stub_step = IncidentActionStubStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    result = await action_stub_step.run(
        IncidentActionStubStepRequest(session_id="session-action-stub-conservative")
    )

    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is True
    assert result.branch is ActionStubBranch.BUILD_ACTION_STUB
    assert result.action_candidate_produced is False
    assert result.approval_required is False
    assert result.runner_status is AgentStatus.RUNNING
    assert result.recommendation_supported is False
    assert result.conservative_due_to_insufficient_evidence is True
    assert result.future_non_read_only_action_blocked_pending_approval is False
    assert result.action_stub_output is not None
    assert result.permission_decision is not None
    assert (
        result.action_stub_output.action_candidate_type
        is ActionCandidateType.NO_ACTIONABLE_STUB_YET
    )
    assert result.verifier_result.status is VerifierStatus.PASS
    assert checkpoint.current_phase == "action_stub_not_actionable"
    assert checkpoint.approval_state.status is ApprovalStatus.NONE
    assert checkpoint.approval_state.future_preconditions == [
        "Keep next actions read-only until deployment-specific causal evidence exists.",
        "Stronger causal evidence is required before proposing a non-read-only candidate.",
    ]
    assert checkpoint.pending_verifier is None


@pytest.mark.asyncio
async def test_incident_action_stub_step_records_insufficient_state_without_recommendation(
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
            session_id="session-action-stub-missing",
            incident_id="incident-action-stub-missing",
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
        IncidentFollowUpStepRequest(session_id="session-action-stub-missing")
    )

    evidence_step = IncidentEvidenceStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    evidence_step.tool.fixtures_path = repo_root / "evals/fixtures/evidence_snapshots.json"
    await evidence_step.run(
        IncidentEvidenceStepRequest(session_id="session-action-stub-missing")
    )

    hypothesis_step = IncidentHypothesisStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await hypothesis_step.run(
        IncidentHypothesisStepRequest(session_id="session-action-stub-missing")
    )

    action_stub_step = IncidentActionStubStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    result = await action_stub_step.run(
        IncidentActionStubStepRequest(session_id="session-action-stub-missing")
    )

    events = JsonlTranscriptStore(result.consulted_artifacts.transcript_path).read_all()
    checkpoint = JsonCheckpointStore(result.checkpoint_path).load()

    assert result.resumed_successfully is False
    assert result.branch is ActionStubBranch.INSUFFICIENT_STATE
    assert result.consumed_recommendation_output is None
    assert result.action_candidate_produced is None
    assert result.approval_required is None
    assert result.runner_status is AgentStatus.VERIFYING
    assert result.verifier_result.status is VerifierStatus.PASS
    assert result.insufficiency_reason is not None
    assert result.consulted_artifacts.previous_phase == "hypothesis_supported"
    assert result.consulted_artifacts.prior_transcript_event_count == 27

    assert isinstance(events[27], ResumeStartedEvent)
    assert isinstance(events[28], ModelStepEvent)
    assert isinstance(events[29], VerifierResultEvent)
    assert isinstance(events[30], CheckpointWrittenEvent)

    assert checkpoint.current_phase == "action_stub_deferred"
    assert checkpoint.approval_state.status is ApprovalStatus.NONE
    assert checkpoint.pending_verifier is None
