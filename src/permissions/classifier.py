"""Risk classification helpers for tool permission decisions."""

from __future__ import annotations

from permissions.models import PermissionAction
from tools.models import ToolDefinition, ToolRiskLevel


def classify_tool(tool: ToolDefinition) -> PermissionAction:
    """Map a tool's declared risk level to a default permission action."""

    match tool.risk_level:
        case ToolRiskLevel.READ_ONLY:
            return PermissionAction.ALLOW
        case ToolRiskLevel.WRITE:
            return PermissionAction.ASK
        case ToolRiskLevel.DANGEROUS:
            return PermissionAction.DENY
