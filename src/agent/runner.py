"""Contracts for top-level agent execution."""

from __future__ import annotations

from typing import Protocol

from agent.state import AgentState


class AgentRunner(Protocol):
    """Owns end-to-end execution for a single run request."""

    async def run(self, initial_state: AgentState) -> AgentState:
        """Run the harness from an initial state to its next stable state."""
