"""Typed models for tool requests, results, and metadata."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from runtime.models import SyntheticFailure

JsonDict: TypeAlias = dict[str, Any]


class ToolRiskLevel(StrEnum):
    """Risk categories used by the permission layer."""

    READ_ONLY = "read_only"
    WRITE = "write"
    DANGEROUS = "dangerous"


class ToolResultStatus(StrEnum):
    """Normalized tool execution outcomes."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ToolDefinition(BaseModel):
    """Static metadata for a registered tool."""

    name: str
    description: str
    risk_level: ToolRiskLevel


class ToolCall(BaseModel):
    """Validated request sent from the loop to a tool."""

    name: str
    arguments: JsonDict = Field(default_factory=dict)


class ToolFailure(BaseModel):
    """Structured failure information for synthetic or runtime errors."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    synthetic_failure: SyntheticFailure | None = None


class ToolResult(BaseModel):
    """Normalized tool output for transcript and verifier consumption."""

    status: ToolResultStatus
    output: JsonDict = Field(default_factory=dict)
    failure: ToolFailure | None = None
