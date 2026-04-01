from agent.state import AgentState, AgentStatus
from permissions.models import PermissionAction
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
