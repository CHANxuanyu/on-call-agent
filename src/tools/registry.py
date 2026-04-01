"""Simple in-memory registry for harness tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from tools.base import Tool
from tools.models import ToolDefinition


@dataclass(slots=True)
class ToolRegistry:
    """Stores tools by name with explicit duplicate protection."""

    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        name = tool.definition.name
        if name in self._tools:
            msg = f"tool already registered: {name}"
            raise ValueError(msg)
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition for _, tool in sorted(self._tools.items()))
