"""Default-safe permission policy skeleton."""

from __future__ import annotations

from permissions.classifier import classify_tool
from permissions.models import (
    EvaluatedActionType,
    PermissionAction,
    PermissionActionCategory,
    PermissionDecision,
    PermissionDecisionProvenance,
    PermissionPolicySource,
    PermissionSafetyBoundary,
)
from tools.models import ToolDefinition, ToolRiskLevel

_DEFAULT_REASONS = {
    PermissionAction.ALLOW: "read-only tools are allowed by default",
    PermissionAction.ASK: "write-capable tools require human approval",
    PermissionAction.DENY: "dangerous tools are denied by default",
}


class PermissionPolicy:
    """Minimal policy surface for future approval workflows."""

    def decide(
        self,
        tool: ToolDefinition,
        *,
        notes: list[str] | None = None,
    ) -> PermissionDecision:
        action = classify_tool(tool)
        return PermissionDecision(
            tool_name=tool.name,
            risk_level=tool.risk_level,
            action=action,
            reason=_DEFAULT_REASONS[action],
            provenance=self._provenance_for(tool=tool, action=action, notes=notes or []),
        )

    def _provenance_for(
        self,
        *,
        tool: ToolDefinition,
        action: PermissionAction,
        notes: list[str],
    ) -> PermissionDecisionProvenance:
        base_notes = [
            "Decision derived from declared tool metadata under the default-safe policy."
        ]
        evaluated_action_type = self._evaluated_action_type(tool)
        if action is PermissionAction.ALLOW:
            return PermissionDecisionProvenance(
                policy_source=PermissionPolicySource.DEFAULT_SAFE_TOOL_RISK,
                action_category=PermissionActionCategory.TOOL_EXECUTION,
                evaluated_action_type=evaluated_action_type,
                approval_required=False,
                conservative_reason=(
                    "The tool is classified as read-only, so this runtime allows it without "
                    "additional approval while keeping non-read-only work out of scope."
                ),
                safety_boundary=PermissionSafetyBoundary.READ_ONLY_ONLY,
                future_preconditions=[
                    "The tool must remain read-only and must not mutate external state.",
                    "Any future non-read-only action requires an explicit approval-gated step.",
                ],
                notes=[*base_notes, *notes],
            )
        if action is PermissionAction.ASK:
            return PermissionDecisionProvenance(
                policy_source=PermissionPolicySource.DEFAULT_SAFE_TOOL_RISK,
                action_category=PermissionActionCategory.TOOL_EXECUTION,
                evaluated_action_type=evaluated_action_type,
                approval_required=True,
                approval_reason=(
                    "The tool is write-capable under the default-safe policy and cannot run "
                    "without explicit human approval."
                ),
                safety_boundary=PermissionSafetyBoundary.HUMAN_APPROVAL_REQUIRED,
                future_preconditions=[
                    "Human approval must be recorded before execution.",
                    "The approved action must stay within the reviewed tool scope.",
                ],
                notes=[*base_notes, *notes],
            )
        return PermissionDecisionProvenance(
            policy_source=PermissionPolicySource.DEFAULT_SAFE_TOOL_RISK,
            action_category=PermissionActionCategory.TOOL_EXECUTION,
            evaluated_action_type=evaluated_action_type,
            approval_required=False,
            denial_reason=(
                "The tool is classified as dangerous and is blocked by the default-safe policy."
            ),
            safety_boundary=PermissionSafetyBoundary.EXECUTION_BLOCKED,
            future_preconditions=[
                "Do not execute this tool under the current runtime policy.",
                "Introduce a narrower, explicitly reviewed slice before reconsidering it.",
            ],
            notes=[*base_notes, *notes],
        )

    def _evaluated_action_type(self, tool: ToolDefinition) -> EvaluatedActionType:
        if tool.risk_level is ToolRiskLevel.READ_ONLY:
            return EvaluatedActionType.READ_ONLY_TOOL
        if tool.risk_level is ToolRiskLevel.WRITE:
            return EvaluatedActionType.WRITE_TOOL
        return EvaluatedActionType.DANGEROUS_TOOL
