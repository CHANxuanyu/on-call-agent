"""Default-safe permission policy skeleton."""

from __future__ import annotations

from permissions.classifier import classify_tool
from permissions.models import PermissionAction, PermissionDecision
from tools.models import ToolDefinition

_DEFAULT_REASONS = {
    PermissionAction.ALLOW: "read-only tools are allowed by default",
    PermissionAction.ASK: "write-capable tools require human approval",
    PermissionAction.DENY: "dangerous tools are denied by default",
}


class PermissionPolicy:
    """Minimal policy surface for future approval workflows."""

    def decide(self, tool: ToolDefinition) -> PermissionDecision:
        action = classify_tool(tool)
        return PermissionDecision(
            tool_name=tool.name,
            risk_level=tool.risk_level,
            action=action,
            reason=_DEFAULT_REASONS[action],
        )
