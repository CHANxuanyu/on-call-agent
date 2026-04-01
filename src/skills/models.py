"""Typed metadata and loaded assets for reusable harness skills."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SkillMetadata(BaseModel):
    """Structured skill contract loaded from repository assets."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    when_to_use: str = Field(min_length=1)
    required_inputs: list[str]
    optional_inputs: list[str]
    expected_outputs: list[str]
    verifier_expectations: list[str]
    permission_notes: list[str]
    examples: list[str]


class SkillAsset(BaseModel):
    """Loaded skill asset with validated metadata and markdown body."""

    model_config = ConfigDict(extra="forbid")

    metadata: SkillMetadata
    path: Path
    instructions_markdown: str = Field(min_length=1)
