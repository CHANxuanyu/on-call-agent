from agent.deployment_rollback_execution import DeploymentRollbackExecutionStep
from permissions.models import (
    EvaluatedActionType,
    PermissionAction,
    PermissionActionCategory,
    PermissionDecision,
    PermissionDecisionProvenance,
    PermissionPolicySource,
    PermissionSafetyBoundary,
)
from permissions.policy import PermissionPolicy
from runtime.inspect import build_audit_event_payload
from tools.implementations.deployment_rollback import DeploymentRollbackExecutorTool
from tools.models import ToolRiskLevel
from transcripts.models import PermissionDecisionEvent


def test_rollback_execution_permission_record_keeps_policy_classification() -> None:
    step = DeploymentRollbackExecutionStep()
    decision = PermissionPolicy().decide(DeploymentRollbackExecutorTool().definition)

    updated_decision = step._approved_execution_permission_decision(decision)

    assert updated_decision.action is PermissionAction.ASK
    assert "approval was already recorded" in updated_decision.reason
    assert "reviewed rollback scope" in updated_decision.reason
    assert "approval was already recorded" in (
        updated_decision.provenance.approval_reason or ""
    ).lower()
    assert "not a fresh request for approval" in " ".join(
        updated_decision.provenance.notes
    )


def test_audit_payload_explains_post_approval_write_permission_semantics() -> None:
    event = PermissionDecisionEvent(
        session_id="session-1",
        step_index=8,
        decision=PermissionDecision(
            tool_name="deployment_rollback_executor",
            risk_level=ToolRiskLevel.WRITE,
            action=PermissionAction.ASK,
            reason=(
                "write-capable tool remains approval-gated by policy; approval was "
                "already recorded, so execution proceeds within the reviewed rollback "
                "scope"
            ),
            provenance=PermissionDecisionProvenance(
                policy_source=PermissionPolicySource.DEFAULT_SAFE_TOOL_RISK,
                action_category=PermissionActionCategory.TOOL_EXECUTION,
                evaluated_action_type=EvaluatedActionType.WRITE_TOOL,
                approval_required=True,
                approval_reason=(
                    "The tool remains approval-gated by policy. Approval was already "
                    "recorded earlier in the session, so this execution is proceeding "
                    "within the reviewed rollback scope."
                ),
                safety_boundary=PermissionSafetyBoundary.HUMAN_APPROVAL_REQUIRED,
                future_preconditions=[
                    "Approval is already recorded for this session before execution begins.",
                    "Execution must stay bounded to the reviewed rollback target and demo "
                    "service scope.",
                ],
                notes=[
                    "This permission record explains policy classification, not a fresh "
                    "request for approval."
                ],
            ),
        ),
    )

    payload = build_audit_event_payload(event)

    assert payload["decision"]["action"] == "ask"
    assert "approval was already recorded" in payload["decision"]["reason"]
    assert "approval was already recorded" in payload["summary"]
