"""Typed state models for agent execution."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    """High-level lifecycle states for a harness run."""

    IDLE = "idle"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentState(BaseModel):
    """Minimal durable state for a resumable execution."""

    session_id: str
    task: str
    status: AgentStatus = AgentStatus.IDLE
    step_index: int = 0
    transcript_path: Path | None = None
    checkpoint_id: str | None = None
    pending_verifiers: list[str] = Field(default_factory=list)
