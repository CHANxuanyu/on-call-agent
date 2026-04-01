"""Contracts for the future agent execution loop."""

from __future__ import annotations

from typing import Protocol

from agent.state import AgentState


class AgentLoop(Protocol):
    """Resumable, step-oriented loop contract for the harness."""

    async def step(self, state: AgentState) -> AgentState:
        """Advance the agent state by one orchestrated step."""
