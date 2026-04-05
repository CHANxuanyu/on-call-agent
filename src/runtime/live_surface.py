"""Operator-facing live incident surface for the deployment-regression slice."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.deployment_outcome_verification import (
    DeploymentOutcomeVerificationStep,
    DeploymentOutcomeVerificationStepRequest,
)
from agent.deployment_rollback_execution import (
    DeploymentRollbackExecutionStep,
    DeploymentRollbackExecutionStepRequest,
)
from agent.incident_action_stub import IncidentActionStubStep, IncidentActionStubStepRequest
from agent.incident_evidence import IncidentEvidenceStep, IncidentEvidenceStepRequest
from agent.incident_follow_up import IncidentFollowUpStep, IncidentFollowUpStepRequest
from agent.incident_hypothesis import IncidentHypothesisStep, IncidentHypothesisStepRequest
from agent.incident_recommendation import (
    IncidentRecommendationStep,
    IncidentRecommendationStepRequest,
)
from agent.incident_triage import IncidentTriageStep, IncidentTriageStepRequest
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import (
    ApprovalState,
    ApprovalStatus,
    JsonCheckpointStore,
    OperatorShellState,
    SessionCheckpoint,
)
from runtime.inspect import build_session_payload
from transcripts.models import ApprovalResolvedEvent, CheckpointWrittenEvent
from transcripts.writer import JsonlTranscriptStore


class DeploymentRegressionStartPayload(BaseModel):
    """Validated live incident payload for the deployment-regression family."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    session_id: str | None = None
    title: str = Field(min_length=1)
    service: str = Field(min_length=1)
    symptoms: list[str] = Field(min_length=1)
    impact_summary: str = Field(min_length=1)
    service_base_url: str = Field(min_length=1)
    expected_bad_version: str = Field(min_length=1)
    expected_previous_version: str = Field(min_length=1)
    severity_hint: str | None = None
    runbook_reference: str | None = None
    ownership_team: str | None = None


def _generated_session_id(incident_id: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    safe_incident_id = incident_id.replace("/", "-").replace("\\", "-")
    return f"{safe_incident_id}-{timestamp}"


async def start_deployment_regression_incident(
    *,
    payload_path: Path,
    skills_root: Path = Path("skills"),
    checkpoint_root: Path = Path("sessions/checkpoints"),
    transcript_root: Path = Path("sessions/transcripts"),
    operator_shell: OperatorShellState | None = None,
    force_new_session: bool = False,
) -> dict[str, Any]:
    payload = DeploymentRegressionStartPayload.model_validate(
        json.loads(payload_path.read_text(encoding="utf-8"))
    )
    session_id = (
        _generated_session_id(payload.incident_id)
        if force_new_session
        else payload.session_id or _generated_session_id(payload.incident_id)
    )

    triage_step = IncidentTriageStep(
        skills_root=skills_root,
        transcript_root=transcript_root,
        checkpoint_root=checkpoint_root,
    )
    await triage_step.run(
        IncidentTriageStepRequest(
            session_id=session_id,
            incident_id=payload.incident_id,
            title=payload.title,
            service=payload.service,
            symptoms=payload.symptoms,
            impact_summary=payload.impact_summary,
            severity_hint=payload.severity_hint,
            recent_deployment=None,
            runbook_reference=payload.runbook_reference,
            ownership_team=payload.ownership_team,
            service_base_url=payload.service_base_url,
            expected_bad_version=payload.expected_bad_version,
            expected_previous_version=payload.expected_previous_version,
            operator_shell=operator_shell or OperatorShellState(),
        )
    )

    follow_up_step = IncidentFollowUpStep(
        transcript_root=transcript_root,
        checkpoint_root=checkpoint_root,
    )
    await follow_up_step.run(IncidentFollowUpStepRequest(session_id=session_id))

    evidence_step = IncidentEvidenceStep(
        transcript_root=transcript_root,
        checkpoint_root=checkpoint_root,
    )
    await evidence_step.run(IncidentEvidenceStepRequest(session_id=session_id))

    hypothesis_step = IncidentHypothesisStep(
        transcript_root=transcript_root,
        checkpoint_root=checkpoint_root,
    )
    await hypothesis_step.run(IncidentHypothesisStepRequest(session_id=session_id))

    recommendation_step = IncidentRecommendationStep(
        transcript_root=transcript_root,
        checkpoint_root=checkpoint_root,
    )
    await recommendation_step.run(IncidentRecommendationStepRequest(session_id=session_id))

    action_stub_step = IncidentActionStubStep(
        transcript_root=transcript_root,
        checkpoint_root=checkpoint_root,
    )
    await action_stub_step.run(IncidentActionStubStepRequest(session_id=session_id))

    artifact_context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=checkpoint_root,
        transcript_root=transcript_root,
    )
    payload_out = build_session_payload(artifact_context)
    payload_out["family"] = "deployment-regression"
    return payload_out


async def resolve_deployment_regression_approval(
    *,
    session_id: str,
    decision: Literal["approve", "deny"],
    reason: str | None = None,
    checkpoint_root: Path = Path("sessions/checkpoints"),
    transcript_root: Path = Path("sessions/transcripts"),
) -> dict[str, Any]:
    artifact_context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=checkpoint_root,
        transcript_root=transcript_root,
    )
    action_stub = artifact_context.latest_verified_action_stub_output().artifact
    if action_stub is None:
        msg = "approval resolution requires a verified rollback candidate in the session"
        raise ValueError(msg)
    if artifact_context.checkpoint.approval_state.status is not ApprovalStatus.PENDING:
        msg = "approval resolution requires a session with approval_status=pending"
        raise ValueError(msg)

    approval_status = (
        ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.DENIED
    )
    requested_action = (
        artifact_context.checkpoint.approval_state.requested_action
        or action_stub.action_candidate_type
    )
    summary = (
        f"Approval {decision}d for {requested_action}."
        if decision == "approve"
        else f"Approval denied for {requested_action}."
    )
    if reason is not None:
        summary = f"{summary} {reason}"

    next_step_index = artifact_context.checkpoint.current_step + 1
    transcript_store = JsonlTranscriptStore(artifact_context.transcript_path)
    transcript_store.append(
        ApprovalResolvedEvent(
            session_id=session_id,
            step_index=next_step_index,
            decision="approved" if decision == "approve" else "denied",
            requested_action=str(requested_action),
            reason=reason,
        )
    )
    checkpoint = SessionCheckpoint(
        checkpoint_id=f"{session_id}-approval-resolution",
        session_id=session_id,
        incident_id=artifact_context.checkpoint.incident_id,
        current_phase="action_stub_approved" if decision == "approve" else "action_stub_denied",
        current_step=next_step_index,
        selected_skills=artifact_context.checkpoint.selected_skills,
        pending_verifier=None,
        approval_state=ApprovalState(
            status=approval_status,
            requested_action=str(requested_action),
            reason=reason,
            future_preconditions=list(action_stub.approval_gate.future_preconditions),
        ),
        operator_shell=artifact_context.checkpoint.operator_shell,
        summary_of_progress=summary,
    )
    checkpoint_path = JsonCheckpointStore(artifact_context.checkpoint_path).write(checkpoint)
    transcript_store.append(
        CheckpointWrittenEvent(
            session_id=session_id,
            step_index=next_step_index,
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_path=checkpoint_path,
            summary_of_progress=checkpoint.summary_of_progress,
        )
    )

    if decision == "approve":
        execution_result = await DeploymentRollbackExecutionStep(
            transcript_root=transcript_root,
            checkpoint_root=checkpoint_root,
        ).run(DeploymentRollbackExecutionStepRequest(session_id=session_id))
        if execution_result.checkpoint.current_phase == "action_execution_completed":
            await DeploymentOutcomeVerificationStep(
                transcript_root=transcript_root,
                checkpoint_root=checkpoint_root,
            ).run(DeploymentOutcomeVerificationStepRequest(session_id=session_id))

    final_context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=checkpoint_root,
        transcript_root=transcript_root,
    )
    payload_out = build_session_payload(final_context)
    payload_out["approval_decision"] = decision
    return payload_out


async def verify_deployment_regression_outcome(
    *,
    session_id: str,
    checkpoint_root: Path = Path("sessions/checkpoints"),
    transcript_root: Path = Path("sessions/transcripts"),
) -> dict[str, Any]:
    await DeploymentOutcomeVerificationStep(
        transcript_root=transcript_root,
        checkpoint_root=checkpoint_root,
    ).run(DeploymentOutcomeVerificationStepRequest(session_id=session_id))
    artifact_context = SessionArtifactContext.load(
        session_id,
        checkpoint_root=checkpoint_root,
        transcript_root=transcript_root,
    )
    payload = build_session_payload(artifact_context)
    payload["verification_rerun"] = True
    return payload


def run_start_deployment_regression_incident(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(start_deployment_regression_incident(**kwargs))


def run_resolve_deployment_regression_approval(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(resolve_deployment_regression_approval(**kwargs))


def run_verify_deployment_regression_outcome(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(verify_deployment_regression_outcome(**kwargs))
