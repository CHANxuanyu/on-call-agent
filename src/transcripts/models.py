"""Structured transcript event models."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from permissions.models import PermissionDecision
from tools.models import ToolCall, ToolResult
from verifiers.base import VerifierRequest, VerifierResult


class TranscriptEventType(StrEnum):
    """Event categories that matter to replay and audit."""

    MODEL_STEP = "model_step"
    TOOL_REQUEST = "tool_request"
    TOOL_RESULT = "tool_result"
    PERMISSION_DECISION = "permission_decision"
    VERIFIER_RESULT = "verifier_result"
    CHECKPOINT_WRITTEN = "checkpoint_written"
    RESUME_STARTED = "resume_started"
    APPROVAL_RESOLVED = "approval_resolved"


class BaseTranscriptEvent(BaseModel):
    """Fields shared across all transcript events."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    step_index: int | None = None


class ModelStepEvent(BaseTranscriptEvent):
    """Reasoning or planning note produced by the model."""

    event_type: Literal["model_step"] = "model_step"
    summary: str
    selected_skills: list[str] = Field(default_factory=list)
    planned_verifiers: list[str] = Field(default_factory=list)


class ToolRequestEvent(BaseTranscriptEvent):
    """Request for a tool execution."""

    event_type: Literal["tool_request"] = "tool_request"
    call_id: str
    tool_call: ToolCall


class ToolResultEvent(BaseTranscriptEvent):
    """Result of a tool execution."""

    event_type: Literal["tool_result"] = "tool_result"
    call_id: str
    tool_name: str
    result: ToolResult


class PermissionDecisionEvent(BaseTranscriptEvent):
    """Recorded policy decision for a tool or action."""

    event_type: Literal["permission_decision"] = "permission_decision"
    decision: PermissionDecision


class VerifierResultEvent(BaseTranscriptEvent):
    """Result of a verifier execution."""

    event_type: Literal["verifier_result"] = "verifier_result"
    verifier_name: str
    request: VerifierRequest
    result: VerifierResult


class CheckpointWrittenEvent(BaseTranscriptEvent):
    """Marker that a durable checkpoint was written."""

    event_type: Literal["checkpoint_written"] = "checkpoint_written"
    checkpoint_id: str
    checkpoint_path: Path
    summary_of_progress: str


class ResumeStartedEvent(BaseTranscriptEvent):
    """Marker that a prior checkpoint is being resumed."""

    event_type: Literal["resume_started"] = "resume_started"
    checkpoint_id: str
    reason: str


class ApprovalResolvedEvent(BaseTranscriptEvent):
    """Marker that a pending approval gate was explicitly resolved."""

    event_type: Literal["approval_resolved"] = "approval_resolved"
    decision: Literal["approved", "denied"]
    requested_action: str
    reason: str | None = None


TranscriptEvent: TypeAlias = Annotated[
    ModelStepEvent
    | ToolRequestEvent
    | ToolResultEvent
    | PermissionDecisionEvent
    | VerifierResultEvent
    | CheckpointWrittenEvent
    | ResumeStartedEvent
    | ApprovalResolvedEvent,
    Field(discriminator="event_type"),
]

_TRANSCRIPT_EVENT_ADAPTER: TypeAdapter[TranscriptEvent] = TypeAdapter(TranscriptEvent)


def serialize_event(event: TranscriptEvent) -> str:
    """Serialize one transcript event to a JSON line."""

    return json.dumps(event.model_dump(mode="json"), sort_keys=True)


def parse_event(data: str | dict[str, Any]) -> TranscriptEvent:
    """Deserialize one transcript event from a JSON line or dict."""

    payload = json.loads(data) if isinstance(data, str) else data
    return _TRANSCRIPT_EVENT_ADAPTER.validate_python(payload)
