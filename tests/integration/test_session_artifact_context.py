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
from context.session_artifacts import (
    SessionArtifactContext,
    SessionReconciliationError,
    TranscriptTailClassification,
)
from permissions.models import (
    EvaluatedActionType,
    PermissionAction,
    PermissionActionCategory,
    PermissionDecision,
    PermissionDecisionProvenance,
    PermissionPolicySource,
    PermissionSafetyBoundary,
)
from runtime.models import SyntheticFailureCode
from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.implementations.incident_action_stub import ActionCandidateType
from tools.implementations.incident_hypothesis import HypothesisType
from tools.implementations.incident_recommendation import RecommendationType
from tools.models import ToolCall, ToolResult, ToolResultStatus, ToolRiskLevel
from transcripts.models import (
    ApprovalResolvedEvent,
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
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus
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


def _append_tail_events(tmp_path: Path, session_id: str, *events: object) -> None:
    store = JsonlTranscriptStore(tmp_path / "transcripts" / f"{session_id}.jsonl")
    for event in events:
        store.append(event)


def _allow_permission_decision(tool_name: str) -> PermissionDecision:
    return PermissionDecision(
        tool_name=tool_name,
        risk_level=ToolRiskLevel.READ_ONLY,
        action=PermissionAction.ALLOW,
        reason="read-only tools are allowed by default",
        provenance=PermissionDecisionProvenance(
            policy_source=PermissionPolicySource.DEFAULT_SAFE_TOOL_RISK,
            action_category=PermissionActionCategory.TOOL_EXECUTION,
            evaluated_action_type=EvaluatedActionType.READ_ONLY_TOOL,
            approval_required=False,
            safety_boundary=PermissionSafetyBoundary.READ_ONLY_ONLY,
        ),
    )


@pytest.mark.asyncio
async def test_session_artifact_context_classifies_bookkeeping_tail_as_clean(
    tmp_path: Path,
) -> None:
    session_id = "session-clean-tail"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id="incident-clean-tail",
    )

    _append_tail_events(
        tmp_path,
        session_id,
        ResumeStartedEvent(
            session_id=session_id,
            step_index=99,
            checkpoint_id=f"{session_id}-incident-action-stub",
            reason="Bookkeeping-only tail.",
        ),
        ModelStepEvent(
            session_id=session_id,
            step_index=99,
            summary="Bookkeeping-only tail should stay ignorable.",
        ),
        PermissionDecisionEvent(
            session_id=session_id,
            step_index=99,
            decision=_allow_permission_decision("incident_action_stub_builder"),
        ),
    )

    context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )

    assert context.reconciliation.tail.classification is TranscriptTailClassification.CLEAN
    assert context.latest_verified_action_stub_output().artifact is not None


@pytest.mark.asyncio
async def test_session_artifact_context_classifies_read_only_tool_tail_as_visible_non_resumable(
    tmp_path: Path,
) -> None:
    session_id = "session-visible-read-only-tail"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id="incident-visible-read-only-tail",
    )

    _append_tail_events(
        tmp_path,
        session_id,
        ToolRequestEvent(
            session_id=session_id,
            step_index=99,
            call_id="tail-read-only-call",
            tool_call=ToolCall(name="incident_action_stub_builder", arguments={}),
            risk_level=ToolRiskLevel.READ_ONLY,
        ),
    )

    context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )

    assert (
        context.reconciliation.tail.classification
        is TranscriptTailClassification.VISIBLE_NON_RESUMABLE
    )
    assert context.reconciliation.tail.details["tool_name"] == "incident_action_stub_builder"
    assert context.latest_verified_action_stub_output().artifact is not None


@pytest.mark.asyncio
async def test_session_artifact_context_classifies_verifier_tail_as_visible_non_resumable(
    tmp_path: Path,
) -> None:
    session_id = "session-visible-verifier-tail"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id="incident-visible-verifier-tail",
    )

    _append_tail_events(
        tmp_path,
        session_id,
        VerifierRequestEvent(
            session_id=session_id,
            step_index=99,
            verifier_name="incident_action_stub_outcome",
            request=VerifierRequest(
                name="incident_action_stub_outcome",
                target="incident-visible-verifier-tail",
                inputs={"branch": "build_action_stub"},
            ),
        ),
    )

    context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
    )

    assert (
        context.reconciliation.tail.classification
        is TranscriptTailClassification.VISIBLE_NON_RESUMABLE
    )
    assert context.reconciliation.tail.details["verifier_name"] == "incident_action_stub_outcome"


@pytest.mark.asyncio
async def test_session_artifact_context_rejects_write_tool_tail(
    tmp_path: Path,
) -> None:
    session_id = "session-unsafe-write-tail"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id="incident-unsafe-write-tail",
    )

    _append_tail_events(
        tmp_path,
        session_id,
        ToolRequestEvent(
            session_id=session_id,
            step_index=99,
            call_id="tail-write-call",
            tool_call=ToolCall(name="deployment_rollback_executor", arguments={}),
            risk_level=ToolRiskLevel.WRITE,
        ),
    )

    with pytest.raises(SessionReconciliationError):
        SessionArtifactContext.load(
            session_id,
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
        )


@pytest.mark.asyncio
async def test_session_artifact_context_rejects_tool_result_tail(
    tmp_path: Path,
) -> None:
    session_id = "session-unsafe-tool-result-tail"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id="incident-unsafe-tool-result-tail",
    )

    _append_tail_events(
        tmp_path,
        session_id,
        ToolResultEvent(
            session_id=session_id,
            step_index=99,
            call_id="tail-read-only-call",
            tool_name="incident_action_stub_builder",
            result=ToolResult(status=ToolResultStatus.SUCCEEDED, output={}),
        ),
    )

    with pytest.raises(SessionReconciliationError):
        SessionArtifactContext.load(
            session_id,
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
        )


@pytest.mark.asyncio
async def test_session_artifact_context_rejects_verifier_result_tail(
    tmp_path: Path,
) -> None:
    session_id = "session-unsafe-verifier-result-tail"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id="incident-unsafe-verifier-result-tail",
    )

    _append_tail_events(
        tmp_path,
        session_id,
        VerifierResultEvent(
            session_id=session_id,
            step_index=99,
            verifier_name="incident_action_stub_outcome",
            request=VerifierRequest(
                name="incident_action_stub_outcome",
                target="incident-unsafe-verifier-result-tail",
                inputs={},
            ),
            result=VerifierResult(
                status=VerifierStatus.PASS,
                summary="Unsafe tail verifier result.",
            ),
        ),
    )

    with pytest.raises(SessionReconciliationError):
        SessionArtifactContext.load(
            session_id,
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
        )


@pytest.mark.asyncio
async def test_session_artifact_context_rejects_approval_resolved_tail(
    tmp_path: Path,
) -> None:
    session_id = "session-unsafe-approval-tail"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id="incident-unsafe-approval-tail",
    )

    _append_tail_events(
        tmp_path,
        session_id,
        ApprovalResolvedEvent(
            session_id=session_id,
            step_index=99,
            decision="approved",
            requested_action="rollback_recent_deployment_candidate",
        ),
    )

    with pytest.raises(SessionReconciliationError):
        SessionArtifactContext.load(
            session_id,
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
        )


@pytest.mark.asyncio
async def test_session_artifact_context_rejects_mismatched_later_checkpoint_tail(
    tmp_path: Path,
) -> None:
    session_id = "session-unsafe-checkpoint-tail"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id="incident-unsafe-checkpoint-tail",
    )

    _append_tail_events(
        tmp_path,
        session_id,
        CheckpointWrittenEvent(
            session_id=session_id,
            step_index=99,
            checkpoint_id="other-checkpoint-id",
            checkpoint_path=tmp_path / "checkpoints" / f"{session_id}.json",
            summary_of_progress="Mismatched later checkpoint.",
        ),
    )

    with pytest.raises(SessionReconciliationError):
        SessionArtifactContext.load(
            session_id,
            checkpoint_root=tmp_path / "checkpoints",
            transcript_root=tmp_path / "transcripts",
        )
