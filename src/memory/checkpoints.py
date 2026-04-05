"""Checkpoint schemas for resumable sessions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tools.models import ToolCall
from verifiers.base import VerifierRequest


class ApprovalStatus(StrEnum):
    """Approval states for pending risky actions."""

    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class OperatorAutonomyMode(StrEnum):
    """Narrow operator shell autonomy modes for the incident runtime."""

    MANUAL = "manual"
    SEMI_AUTO = "semi-auto"
    AUTO_SAFE = "auto-safe"


class ApprovalState(BaseModel):
    """Current approval state for the session."""

    model_config = ConfigDict(extra="forbid")

    status: ApprovalStatus = ApprovalStatus.NONE
    requested_action: str | None = None
    reason: str | None = None
    future_preconditions: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OperatorShellState(BaseModel):
    """Durable operator shell state stored alongside the current checkpoint."""

    model_config = ConfigDict(extra="forbid")

    requested_mode: OperatorAutonomyMode = OperatorAutonomyMode.MANUAL
    effective_mode: OperatorAutonomyMode = OperatorAutonomyMode.MANUAL
    mode_reason: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PendingVerifier(BaseModel):
    """Durable pointer to a verifier that still needs to run."""

    model_config = ConfigDict(extra="forbid")

    verifier_name: str
    request: VerifierRequest


class CheckpointRecord(BaseModel):
    """Minimal durable checkpoint metadata."""

    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str
    session_id: str
    step_index: int
    summary: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SessionCheckpoint(BaseModel):
    """On-disk resumable session checkpoint document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    checkpoint_id: str
    session_id: str
    incident_id: str
    current_phase: str
    current_step: int
    selected_skills: list[str] = Field(default_factory=list)
    pending_tool_call: ToolCall | None = None
    pending_verifier: PendingVerifier | None = None
    approval_state: ApprovalState = Field(default_factory=ApprovalState)
    operator_shell: OperatorShellState = Field(default_factory=OperatorShellState)
    latest_checkpoint_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary_of_progress: str = Field(min_length=1)


class JsonCheckpointStore:
    """Simple local JSON checkpoint store for resumable session state."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, checkpoint: SessionCheckpoint) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(checkpoint.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self.path

    def load(self) -> SessionCheckpoint:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return SessionCheckpoint.model_validate(payload)
