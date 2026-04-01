"""Typed LLM request and response models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class LLMMessageRole(StrEnum):
    """Supported chat roles for the future model interface."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class LLMMessage(BaseModel):
    """One structured message exchanged with an LLM backend."""

    role: LLMMessageRole
    content: str


class LLMRequest(BaseModel):
    """Minimal request envelope for a model invocation."""

    model: str
    messages: list[LLMMessage] = Field(default_factory=list)


class LLMResponse(BaseModel):
    """Minimal structured response from a model backend."""

    model: str
    output_text: str
    stop_reason: str | None = None
