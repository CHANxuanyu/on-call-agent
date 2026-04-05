from datetime import UTC, datetime
from pathlib import Path

from memory.checkpoints import (
    ApprovalState,
    ApprovalStatus,
    JsonCheckpointStore,
    SessionCheckpoint,
)
from memory.incident_working_memory import (
    IncidentWorkingMemory,
    JsonIncidentWorkingMemoryStore,
    LeadingHypothesisSnapshot,
    RecommendationSnapshot,
)
from runtime.assistant_api import AssistantIntent, AssistantSourceKind, SessionAssistantAPI
from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.implementations.incident_action_stub import (
    ActionCandidateType,
    ApprovalGateOutcome,
    IncidentActionStubOutput,
)
from tools.implementations.incident_hypothesis import (
    HypothesisConfidence,
    HypothesisType,
    IncidentHypothesisOutput,
)
from tools.implementations.incident_recommendation import (
    IncidentRecommendationOutput,
    RecommendationApprovalLevel,
    RecommendationRiskLevel,
    RecommendationType,
)
from tools.models import ToolCall, ToolResult, ToolResultStatus
from transcripts.models import ToolRequestEvent, ToolResultEvent, VerifierResultEvent
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import VerifierRequest, VerifierResult, VerifierStatus


def _write_pending_deployment_session(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
) -> None:
    checkpoint_root = tmp_path / "checkpoints"
    transcript_root = tmp_path / "transcripts"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    transcript_root.mkdir(parents=True, exist_ok=True)

    JsonCheckpointStore(checkpoint_root / f"{session_id}.json").write(
        SessionCheckpoint(
            checkpoint_id=f"{session_id}-checkpoint",
            session_id=session_id,
            incident_id=incident_id,
            current_phase="action_stub_pending_approval",
            current_step=6,
            selected_skills=["incident-triage"],
            approval_state=ApprovalState(
                status=ApprovalStatus.PENDING,
                requested_action="rollback_recent_deployment_candidate",
                reason="Operator review required for rollback.",
            ),
            latest_checkpoint_time=datetime(2026, 4, 5, 12, 0, tzinfo=UTC),
            summary_of_progress="Rollback candidate is pending approval.",
        )
    )

    evidence_output = EvidenceReadOutput(
        incident_id=incident_id,
        service="payments-api",
        investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
        snapshot_id="live-deployment-2.1.0",
        evidence_source=(
            "http://127.0.0.1:8001/deployment,http://127.0.0.1:8001/health,"
            "http://127.0.0.1:8001/metrics"
        ),
        evidence_summary=(
            "Live runtime evidence shows deployment 2.1.0 completed 12 minutes before the "
            "alert and degraded request timeout handling."
        ),
        observations=[
            "Deployment endpoint reports current_version 2.1.0 and previous_version 2.0.9.",
            (
                "Deployment endpoint reports the rollout as recent and before alert "
                "triage: bad_release_active=True."
            ),
            "Health endpoint reports status=degraded, healthy=False, error_rate=0.41.",
        ],
        recommended_next_read_only_action="Inspect rollback preconditions for payments-api.",
    )
    hypothesis_output = IncidentHypothesisOutput(
        incident_id=incident_id,
        service="payments-api",
        evidence_snapshot_id=evidence_output.snapshot_id,
        evidence_investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
        hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
        evidence_supported=True,
        confidence=HypothesisConfidence.MEDIUM,
        rationale_summary=(
            "Evidence supports a recent deployment regression affecting payments-api."
        ),
        supporting_evidence_fields=["snapshot_id", "evidence_summary", "observations"],
        unresolved_gaps=[
            "Need rollback or mitigation confirmation before treating the regression as validated."
        ],
        recommended_next_action=(
            "Review the deployment diff and validate rollback options for payments-api."
        ),
        more_investigation_required=True,
    )
    recommendation_output = IncidentRecommendationOutput(
        incident_id=incident_id,
        service="payments-api",
        consumed_hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
        recommendation_type=RecommendationType.VALIDATE_RECENT_DEPLOYMENT,
        action_summary=(
            "Validate rollback readiness for the recent deployment on payments-api and "
            "prepare an approval review if rollback preconditions hold."
        ),
        justification=(
            "Evidence supports a recent deployment regression. Validate rollback readiness "
            "before proposing the bounded rollback candidate."
        ),
        risk_level=RecommendationRiskLevel.MEDIUM,
        required_approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
        preconditions=[
            "Confirm the currently deployed version still matches the suspected bad release.",
            "Confirm the previous version is a known-good rollback target.",
            "Keep all non-read-only actions blocked until on-call lead approval is recorded.",
        ],
        supporting_artifact_refs=[
            "hypothesis:deployment_regression",
            f"evidence:{evidence_output.snapshot_id}",
        ],
        expected_outcome=(
            "A verified rollback-readiness assessment can justify a later approval-ready "
            "rollback candidate for payments-api."
        ),
        rollback_or_safety_notes=(
            "Do not execute rollback without human approval, a version match check, and a "
            "bounded rollback safety check."
        ),
        more_investigation_required=True,
    )
    action_stub_output = IncidentActionStubOutput(
        incident_id=incident_id,
        service="payments-api",
        consumed_recommendation_type=RecommendationType.VALIDATE_RECENT_DEPLOYMENT,
        action_candidate_type=ActionCandidateType.ROLLBACK_RECENT_DEPLOYMENT_CANDIDATE,
        action_candidate_created=True,
        action_summary=(
            "Propose a rollback to the previous known-good version for payments-api "
            "pending approval."
        ),
        justification=(
            "The runtime has enough verifier-backed evidence to record a bounded rollback "
            "candidate, but it must remain blocked pending approval."
        ),
        risk_level=RecommendationRiskLevel.MEDIUM,
        supporting_artifact_refs=recommendation_output.supporting_artifact_refs,
        expected_outcome=(
            "Approval can authorize the bounded rollback candidate for payments-api."
        ),
        safety_notes=(
            "This candidate remains blocked until human approval is recorded."
        ),
        approval_gate=ApprovalGateOutcome(
            approval_required=True,
            approval_reason="Rollback candidate requires explicit on-call lead approval.",
            proposed_action_type=ActionCandidateType.ROLLBACK_RECENT_DEPLOYMENT_CANDIDATE,
            allowed_without_approval=False,
            approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
            future_preconditions=recommendation_output.preconditions,
        ),
        future_non_read_only_action_blocked_pending_approval=True,
        more_investigation_required=True,
    )

    store = JsonlTranscriptStore(transcript_root / f"{session_id}.jsonl")
    store.append(
        ToolRequestEvent(
            session_id=session_id,
            step_index=1,
            call_id="triage-call",
            tool_call=ToolCall(
                name="incident_payload_summary",
                arguments={
                    "incident_id": incident_id,
                    "title": "payments-api unhealthy after deploy",
                    "service": "payments-api",
                    "symptoms": ["health endpoint is degraded"],
                    "impact_summary": "Checkout traffic is degraded.",
                    "service_base_url": "http://127.0.0.1:8001",
                    "expected_bad_version": "2.1.0",
                    "expected_previous_version": "2.0.9",
                },
            ),
        )
    )
    _append_verified_tool_artifact(
        store,
        session_id=session_id,
        step_index=3,
        tool_name="evidence_bundle_reader",
        verifier_name="incident_evidence_read_outcome",
        output=evidence_output.model_dump(mode="json"),
        summary="Live deployment evidence is verifier-backed.",
    )
    _append_verified_tool_artifact(
        store,
        session_id=session_id,
        step_index=4,
        tool_name="incident_hypothesis_builder",
        verifier_name="incident_hypothesis_outcome",
        output=hypothesis_output.model_dump(mode="json"),
        summary="Deployment-regression hypothesis is supported.",
    )
    _append_verified_tool_artifact(
        store,
        session_id=session_id,
        step_index=5,
        tool_name="incident_recommendation_builder",
        verifier_name="incident_recommendation_outcome",
        output=recommendation_output.model_dump(mode="json"),
        summary="Rollback-readiness recommendation is supported.",
    )
    _append_verified_tool_artifact(
        store,
        session_id=session_id,
        step_index=6,
        tool_name="incident_action_stub_builder",
        verifier_name="incident_action_stub_outcome",
        output=action_stub_output.model_dump(mode="json"),
        summary="Rollback candidate is pending operator approval.",
    )


def _append_verified_tool_artifact(
    store: JsonlTranscriptStore,
    *,
    session_id: str,
    step_index: int,
    tool_name: str,
    verifier_name: str,
    output: dict[str, object],
    summary: str,
) -> None:
    call_id = f"{tool_name}-call-{step_index}"
    store.append(
        ToolRequestEvent(
            session_id=session_id,
            step_index=step_index,
            call_id=call_id,
            tool_call=ToolCall(name=tool_name, arguments={}),
        )
    )
    store.append(
        ToolResultEvent(
            session_id=session_id,
            step_index=step_index,
            call_id=call_id,
            tool_name=tool_name,
            result=ToolResult(status=ToolResultStatus.SUCCEEDED, output=output),
        )
    )
    store.append(
        VerifierResultEvent(
            session_id=session_id,
            step_index=step_index,
            verifier_name=verifier_name,
            request=VerifierRequest(name=verifier_name, target=session_id),
            result=VerifierResult(status=VerifierStatus.PASS, summary=summary),
        )
    )


def _write_working_memory_snapshot(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
) -> None:
    JsonIncidentWorkingMemoryStore.for_incident(
        incident_id,
        root=tmp_path / "working_memory",
    ).write(
        IncidentWorkingMemory(
            incident_id=incident_id,
            service="payments-api",
            source_session_id=session_id,
            source_checkpoint_id=f"{session_id}-checkpoint",
            source_phase="recommendation_supported",
            last_updated_by_step="incident_recommendation",
            last_updated_at=datetime(2026, 4, 5, 12, 5, tzinfo=UTC),
            leading_hypothesis=LeadingHypothesisSnapshot(
                hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
                summary="Recent deployment remains the leading hypothesis.",
                evidence_supported=True,
            ),
            unresolved_gaps=[
                "Need rollback or mitigation confirmation before treating the "
                "regression as validated."
            ],
            important_evidence_references=["evidence:live-deployment-2.1.0"],
            recommendation=RecommendationSnapshot(
                recommendation_type=RecommendationType.VALIDATE_RECENT_DEPLOYMENT,
                summary=(
                    "Validate rollback readiness before proposing the bounded "
                    "rollback candidate."
                ),
                required_approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
                more_investigation_required=True,
            ),
            compact_handoff_note=(
                "Working memory tracks the current deployment-regression assessment for "
                "payments-api."
            ),
        )
    )


def test_assistant_explains_pending_approval_blocker_from_runtime_truth(
    tmp_path: Path,
) -> None:
    session_id = "session-assistant-blocked"
    _write_pending_deployment_session(
        tmp_path,
        session_id=session_id,
        incident_id="incident-assistant-blocked",
    )
    assistant = SessionAssistantAPI(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    )

    response = assistant.respond(session_id, prompt="Why is this session blocked?")

    assert response.intent is AssistantIntent.BLOCKED_OR_READY
    assert "blocked on explicit human approval" in response.answer
    assert response.grounding.current_prompt_only is True
    assert response.grounding.chat_history_persisted is False
    assert {
        source.kind for source in response.grounding.authority_sources
    } == {
        AssistantSourceKind.CHECKPOINT,
        AssistantSourceKind.TRANSCRIPT,
        AssistantSourceKind.SESSION_ARTIFACT_CONTEXT,
    }
    assert response.grounding.supporting_sources == []


def test_assistant_summarizes_evidence_from_verified_artifacts(
    tmp_path: Path,
) -> None:
    session_id = "session-assistant-evidence"
    _write_pending_deployment_session(
        tmp_path,
        session_id=session_id,
        incident_id="incident-assistant-evidence",
    )
    assistant = SessionAssistantAPI(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    )

    response = assistant.respond(
        session_id,
        prompt="What evidence supports the current recommendation?",
    )

    assert response.intent is AssistantIntent.EVIDENCE_SUMMARY
    assert "Verified evidence summary:" in response.answer
    assert "deployment 2.1.0 completed 12 minutes before the alert" in response.answer
    assert "Current recommendation summary:" in response.answer
    assert any(
        source.kind is AssistantSourceKind.SESSION_ARTIFACT_CONTEXT
        for source in response.grounding.authority_sources
    )


def test_assistant_handoff_draft_is_non_persistent_and_session_scoped(
    tmp_path: Path,
) -> None:
    session_id = "session-assistant-handoff"
    incident_id = "incident-assistant-handoff"
    _write_pending_deployment_session(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )
    assistant = SessionAssistantAPI(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    )

    response = assistant.respond(
        session_id,
        prompt="Draft a handoff summary for the next operator.",
    )

    assert response.intent is AssistantIntent.HANDOFF_DRAFT
    assert "This is a draft derived from current runtime truth" in response.answer
    assert response.grounding.chat_history_persisted is False
    assert list((tmp_path / "handoffs").glob("*.json")) == []


def test_assistant_treats_working_memory_as_supporting_context_only(
    tmp_path: Path,
) -> None:
    session_id = "session-assistant-working-memory"
    incident_id = "incident-assistant-working-memory"
    _write_pending_deployment_session(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )
    _write_working_memory_snapshot(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )
    assistant = SessionAssistantAPI(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    )

    response = assistant.respond(
        session_id,
        prompt="What evidence supports the current recommendation?",
    )

    assert response.intent is AssistantIntent.EVIDENCE_SUMMARY
    assert AssistantSourceKind.WORKING_MEMORY not in {
        source.kind for source in response.grounding.authority_sources
    }
    assert AssistantSourceKind.WORKING_MEMORY in {
        source.kind for source in response.grounding.supporting_sources
    }


def test_assistant_fails_closed_on_generic_planner_prompt(
    tmp_path: Path,
) -> None:
    session_id = "session-assistant-unsupported"
    _write_pending_deployment_session(
        tmp_path,
        session_id=session_id,
        incident_id="incident-assistant-unsupported",
    )
    assistant = SessionAssistantAPI(
        checkpoint_root=tmp_path / "checkpoints",
        transcript_root=tmp_path / "transcripts",
        handoff_root=tmp_path / "handoffs",
    )

    response = assistant.respond(
        session_id,
        prompt="Plan a remediation strategy across all systems.",
    )

    assert response.intent is AssistantIntent.UNSUPPORTED
    assert "only explains the current session truth" in response.answer
