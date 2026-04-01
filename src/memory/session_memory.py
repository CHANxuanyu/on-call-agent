"""Session-local memory models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SessionMemory(BaseModel):
    """Compact summary of a session's durable working context."""

    session_id: str
    timeline: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    handoff_summary: str | None = None
