"""Typed runtime models for structured synthetic failures."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SyntheticFailureSource(StrEnum):
    """Runtime component responsible for a structured synthetic failure."""

    TOOL = "tool"
    VERIFIER = "verifier"
    STEP = "step"
    CONTEXT = "context"


class SyntheticFailureCode(StrEnum):
    """Narrow synthetic failure codes used across transcripted runtime paths."""

    REQUIRED_ARTIFACT_UNUSABLE = "required_artifact_unusable"
    STEP_INTERRUPTED = "step_interrupted"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    TOOL_RESULT_INVALID = "tool_result_invalid"
    TOOL_OUTPUT_VALIDATION_FAILED = "tool_output_validation_failed"
    VERIFIER_EXECUTION_FAILED = "verifier_execution_failed"
    VERIFIER_RESULT_INVALID = "verifier_result_invalid"
    VERIFIER_RESULT_MISSING = "verifier_result_missing"


class SyntheticFailure(BaseModel):
    """Structured synthetic failure that keeps failure paths replayable."""

    model_config = ConfigDict(extra="forbid")

    code: SyntheticFailureCode
    source: SyntheticFailureSource
    step_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    tool_name: str | None = None
    verifier_name: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
