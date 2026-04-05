from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from context.handoff import (
    ApprovalHandoffSummary,
    HandoffArtifactReference,
    HandoffArtifactSource,
    IncidentHandoffContext,
    IncidentHandoffContextAssembler,
)
from memory.checkpoints import ApprovalState, ApprovalStatus
from memory.incident_working_memory import (
    IncidentWorkingMemory,
    LeadingHypothesisSnapshot,
    RecommendationSnapshot,
)
from tools.implementations.deployment_outcome_probe import DeploymentOutcomeProbeOutput
from tools.implementations.deployment_rollback import DeploymentRollbackExecutionOutput
from tools.implementations.follow_up_investigation import InvestigationTarget
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


def test_handoff_context_requires_non_empty_attention_point() -> None:
    with pytest.raises(ValidationError):
        IncidentHandoffContext(
            incident_id="incident-handoff",
            service="payments-api",
            current_phase="recommendation_supported",
            progress_summary="Recommendation step completed.",
            approval=ApprovalHandoffSummary(status=ApprovalStatus.NONE),
            current_operator_attention_point="",
            compact_handoff_note="Recommendation is available for operator review.",
            derived_from=[
                HandoffArtifactReference(
                    source=HandoffArtifactSource.CHECKPOINT,
                    artifact_name="session_checkpoint",
                    path=Path("sessions/checkpoints/example.json"),
                )
            ],
        )


def test_handoff_context_requires_durable_references() -> None:
    with pytest.raises(ValidationError):
        IncidentHandoffContext(
            incident_id="incident-handoff",
            service="payments-api",
            current_phase="recommendation_supported",
            progress_summary="Recommendation step completed.",
            approval=ApprovalHandoffSummary(status=ApprovalStatus.NONE),
            current_operator_attention_point="Review the recommendation.",
            compact_handoff_note="Recommendation is available for operator review.",
            derived_from=[],
        )


def test_handoff_context_prefers_current_phase_working_memory_for_resolved_outcome() -> None:
    working_memory = IncidentWorkingMemory(
        incident_id="incident-handoff",
        service="payments-api",
        source_session_id="session-handoff",
        source_checkpoint_id="session-handoff-outcome",
        source_phase="outcome_verification_succeeded",
        last_updated_by_step="deployment_outcome_verification",
        leading_hypothesis=LeadingHypothesisSnapshot(
            hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
            summary="Evidence supports a deployment regression for payments-api.",
            evidence_supported=True,
        ),
        unresolved_gaps=[],
        important_evidence_references=[
            "evidence:live-deployment-2.1.0",
            "rollback:2.1.0->2.0.9",
        ],
        recommendation=RecommendationSnapshot(
            recommendation_type=RecommendationType.VALIDATE_RECENT_DEPLOYMENT,
            summary=(
                "Validate rollback readiness for the recent deployment on payments-api "
                "and prepare an approval review if rollback preconditions hold."
            ),
            required_approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
            more_investigation_required=False,
        ),
        compact_handoff_note=(
            "Rollback executed for payments-api from 2.1.0 to 2.0.9. Outcome "
            "verification passed with health_status=healthy, error_rate=0.01, "
            "timeout_rate=0.00."
        ),
    )
    hypothesis_output = IncidentHypothesisOutput(
        incident_id="incident-handoff",
        service="payments-api",
        evidence_snapshot_id="live-deployment-2.1.0",
        evidence_investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
        hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
        evidence_supported=True,
        confidence=HypothesisConfidence.MEDIUM,
        rationale_summary="Evidence supports a deployment regression for payments-api.",
        supporting_evidence_fields=["snapshot_id", "observations"],
        unresolved_gaps=[
            "Need rollback or mitigation confirmation before treating the regression as validated."
        ],
        recommended_next_action="Review the deployment diff and validate rollback options.",
        more_investigation_required=True,
    )
    recommendation_output = SimpleNamespace(
        artifact=IncidentRecommendationOutput(
            incident_id="incident-handoff",
            service="payments-api",
            consumed_hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
            recommendation_type=RecommendationType.VALIDATE_RECENT_DEPLOYMENT,
            action_summary=(
                "Validate rollback readiness for the recent deployment on payments-api "
                "and prepare an approval review if rollback preconditions hold."
            ),
            justification="Deployment evidence supports a regression hypothesis.",
            risk_level=RecommendationRiskLevel.MEDIUM,
            required_approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
            preconditions=[
                "Confirm the currently deployed version still matches the suspected bad release."
            ],
            supporting_artifact_refs=[
                "hypothesis:deployment_regression",
                "evidence:live-deployment-2.1.0",
            ],
            expected_outcome=(
                "A verified rollback-readiness assessment can justify a later "
                "approval-ready rollback candidate for payments-api."
            ),
            rollback_or_safety_notes="Do not execute rollback without human approval.",
            more_investigation_required=True,
        )
    )
    action_execution_output = DeploymentRollbackExecutionOutput(
        incident_id="incident-handoff",
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
    )
    outcome_output = DeploymentOutcomeProbeOutput(
        incident_id="incident-handoff",
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
            "Runtime probe sees version 2.0.9, health_status=healthy, error_rate=0.01, "
            "timeout_rate=0.00."
        ),
    )
    artifact_context = SimpleNamespace(
        checkpoint_path=Path("sessions/checkpoints/session-handoff.json"),
        transcript_path=Path("sessions/transcripts/session-handoff.jsonl"),
        working_memory_path=Path("sessions/working_memory/incident-handoff.json"),
        checkpoint=SimpleNamespace(
            incident_id="incident-handoff",
            current_phase="outcome_verification_succeeded",
            summary_of_progress=(
                "Outcome verification probed version 2.0.9 with health_status=healthy. "
                "Verifier status: pass."
            ),
            approval_state=ApprovalState(
                status=ApprovalStatus.APPROVED,
                requested_action="rollback_recent_deployment_candidate",
                reason="Rollback approved for the live demo target.",
            ),
            checkpoint_id="session-handoff-outcome",
        ),
        latest_verified_triage_output=lambda: SimpleNamespace(artifact=None),
        latest_verified_follow_up_output=lambda: SimpleNamespace(artifact=None),
        latest_verified_evidence_output=lambda: SimpleNamespace(artifact=None),
        latest_verified_hypothesis_output=lambda: SimpleNamespace(artifact=hypothesis_output),
        latest_verified_recommendation_output=lambda: recommendation_output,
        latest_verified_action_stub_output=lambda: SimpleNamespace(artifact=None),
        latest_verified_action_execution_output=lambda: SimpleNamespace(
            artifact=action_execution_output
        ),
        latest_verified_outcome_verification_output=lambda: SimpleNamespace(
            artifact=outcome_output
        ),
        latest_incident_working_memory=lambda: working_memory,
    )

    handoff = IncidentHandoffContextAssembler().assemble(artifact_context)

    assert handoff.unresolved_gaps == []
    assert handoff.compact_handoff_note == working_memory.compact_handoff_note
    assert handoff.current_operator_attention_point == outcome_output.summary
    assert any(
        reference.source is HandoffArtifactSource.INCIDENT_WORKING_MEMORY
        and reference.detail == "outcome_verification_succeeded"
        for reference in handoff.derived_from
    )
