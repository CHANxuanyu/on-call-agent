"""Protocol for future LLM backends."""

from __future__ import annotations

from typing import Protocol

import httpx

from llm.models import LLMRequest, LLMResponse


class LLMClient(Protocol):
    """Stable client surface used by the agent loop."""

    http_client: httpx.AsyncClient | None

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute a completion request."""
