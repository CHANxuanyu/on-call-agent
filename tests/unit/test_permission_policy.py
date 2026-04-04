import pytest
from pydantic import ValidationError

from agent.state import AgentState, AgentStatus
from permissions.models import (
    EvaluatedActionType,
    PermissionAction,
    PermissionActionCategory,
    PermissionDecisionProvenance,
    PermissionPolicySource,
    PermissionSafetyBoundary,
)
from permissions.policy import PermissionPolicy
from tools.models import ToolDefinition, ToolRiskLevel


def test_agent_state_defaults_are_minimal() -> None:
    state = AgentState(session_id="session-1", task="Investigate elevated 5xx")

    assert state.status is AgentStatus.IDLE
    assert state.step_index == 0
    assert state.pending_verifiers == []


def test_default_permission_policy_allows_read_only_tools() -> None:
    policy = PermissionPolicy()
    tool = ToolDefinition(
        name="read_logs",
        description="Read application logs",
        risk_level=ToolRiskLevel.READ_ONLY,
    )

    decision = policy.decide(tool)

    assert decision.action is PermissionAction.ALLOW
    assert decision.tool_name == "read_logs"
    assert decision.provenance.policy_source is PermissionPolicySource.DEFAULT_SAFE_TOOL_RISK
    assert decision.provenance.action_category is PermissionActionCategory.TOOL_EXECUTION
    assert decision.provenance.evaluated_action_type is EvaluatedActionType.READ_ONLY_TOOL
    assert decision.provenance.approval_required is False
    assert decision.provenance.safety_boundary is PermissionSafetyBoundary.READ_ONLY_ONLY
    assert decision.provenance.future_preconditions


def test_default_permission_policy_requires_approval_for_write_tools() -> None:
    policy = PermissionPolicy()
    tool = ToolDefinition(
        name="restart_service",
        description="Restart an application service",
        risk_level=ToolRiskLevel.WRITE,
    )

    decision = policy.decide(tool)

    assert decision.action is PermissionAction.ASK
    assert decision.provenance.evaluated_action_type is EvaluatedActionType.WRITE_TOOL
    assert decision.provenance.approval_required is True
    assert decision.provenance.approval_reason is not None
    assert (
        decision.provenance.safety_boundary
        is PermissionSafetyBoundary.HUMAN_APPROVAL_REQUIRED
    )


def test_default_permission_policy_denies_dangerous_tools() -> None:
    policy = PermissionPolicy()
    tool = ToolDefinition(
        name="wipe_host",
        description="Destroy the current host",
        risk_level=ToolRiskLevel.DANGEROUS,
    )

    decision = policy.decide(tool)

    assert decision.action is PermissionAction.DENY
    assert decision.provenance.evaluated_action_type is EvaluatedActionType.DANGEROUS_TOOL
    assert decision.provenance.denial_reason is not None
    assert decision.provenance.approval_required is False
    assert decision.provenance.safety_boundary is PermissionSafetyBoundary.EXECUTION_BLOCKED


def test_permission_decision_provenance_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PermissionDecisionProvenance.model_validate(
            {
                "policy_source": "default_safe_tool_risk",
                "action_category": "tool_execution",
                "evaluated_action_type": "read_only_tool",
                "approval_required": False,
                "safety_boundary": "read_only_only",
                "unexpected": "nope",
            }
        )
