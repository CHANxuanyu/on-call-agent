"""Models for permission decisions and approval flow state."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from tools.models import ToolRiskLevel


class PermissionAction(StrEnum):
    """Possible outcomes of a permission check."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionPolicySource(StrEnum):
    """Stable source labels for permission provenance."""

    DEFAULT_SAFE_TOOL_RISK = "default_safe_tool_risk"


class PermissionActionCategory(StrEnum):
    """Broad categories evaluated by the permission layer."""

    TOOL_EXECUTION = "tool_execution"


class EvaluatedActionType(StrEnum):
    """Concrete action types currently evaluated by the permission layer."""

    READ_ONLY_TOOL = "read_only_tool"
    WRITE_TOOL = "write_tool"
    DANGEROUS_TOOL = "dangerous_tool"


class PermissionSafetyBoundary(StrEnum):
    """Safety boundary enforced by the current permission decision."""

    READ_ONLY_ONLY = "read_only_only"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required"
    EXECUTION_BLOCKED = "execution_blocked"


class PermissionDecisionProvenance(BaseModel):
    """Structured rationale for how a permission decision was produced."""

    model_config = ConfigDict(extra="forbid")

    policy_source: PermissionPolicySource
    action_category: PermissionActionCategory
    evaluated_action_type: EvaluatedActionType
    approval_required: bool
    approval_reason: str | None = None
    denial_reason: str | None = None
    conservative_reason: str | None = None
    safety_boundary: PermissionSafetyBoundary
    future_preconditions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PermissionDecision(BaseModel):
    """Audit-friendly record of a tool permission decision."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    risk_level: ToolRiskLevel
    action: PermissionAction
    reason: str
    provenance: PermissionDecisionProvenance
