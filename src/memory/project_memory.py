"""Project-level memory records for durable operational knowledge."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ProjectMemoryRecord(BaseModel):
    """Stable memory item derived from prior sessions or documentation."""

    key: str
    value: str
    source: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
