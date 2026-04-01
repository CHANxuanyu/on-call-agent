"""Base protocol for harness-managed tools."""

from __future__ import annotations

from typing import Protocol

from tools.models import ToolCall, ToolDefinition, ToolResult


class Tool(Protocol):
    """Stable contract for a tool exposed to the agent harness."""

    @property
    def definition(self) -> ToolDefinition:
        """Return the tool's static metadata."""

    async def execute(self, call: ToolCall) -> ToolResult:
        """Execute a validated tool call."""
