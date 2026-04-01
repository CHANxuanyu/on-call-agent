"""Models for permission decisions and approval flow state."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from tools.models import ToolRiskLevel


class PermissionAction(StrEnum):
    """Possible outcomes of a permission check."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionDecision(BaseModel):
    """Audit-friendly record of a tool permission decision."""

    tool_name: str
    risk_level: ToolRiskLevel
    action: PermissionAction
    reason: str
