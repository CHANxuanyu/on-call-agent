"""Incident working-memory models and local JSON persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tools.implementations.incident_hypothesis import HypothesisType
from tools.implementations.incident_recommendation import (
    RecommendationApprovalLevel,
    RecommendationType,
)


class LeadingHypothesisSnapshot(BaseModel):
    """Compact verifier-backed hypothesis snapshot for the active incident."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_type: HypothesisType
    summary: str = Field(min_length=1)
    evidence_supported: bool


class RecommendationSnapshot(BaseModel):
    """Compact verifier-backed recommendation snapshot for the active incident."""

    model_config = ConfigDict(extra="forbid")

    recommendation_type: RecommendationType
    summary: str = Field(min_length=1)
    required_approval_level: RecommendationApprovalLevel
    more_investigation_required: bool


class IncidentWorkingMemory(BaseModel):
    """Latest semantic working-memory snapshot for one incident."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    incident_id: str = Field(min_length=1)
    service: str = Field(min_length=1)
    source_session_id: str = Field(min_length=1)
    source_checkpoint_id: str = Field(min_length=1)
    source_phase: str = Field(min_length=1)
    last_updated_by_step: str = Field(min_length=1)
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    leading_hypothesis: LeadingHypothesisSnapshot | None = None
    unresolved_gaps: list[str] = Field(default_factory=list)
    important_evidence_references: list[str] = Field(default_factory=list)
    recommendation: RecommendationSnapshot | None = None
    compact_handoff_note: str = Field(min_length=1)


def incident_working_memory_path(
    incident_id: str,
    *,
    root: Path = Path("sessions/working_memory"),
) -> Path:
    """Return the deterministic JSON path for one incident working-memory snapshot."""

    safe_incident_id = incident_id.replace("/", "__").replace("\\", "__")
    return root / f"{safe_incident_id}.json"


class JsonIncidentWorkingMemoryStore:
    """Simple local JSON store for incident working-memory snapshots."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_incident(
        cls,
        incident_id: str,
        *,
        root: Path = Path("sessions/working_memory"),
    ) -> JsonIncidentWorkingMemoryStore:
        return cls(incident_working_memory_path(incident_id, root=root))

    def write(self, memory: IncidentWorkingMemory) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(memory.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self.path

    def load(self) -> IncidentWorkingMemory:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return IncidentWorkingMemory.model_validate(payload)

    def load_optional(self) -> IncidentWorkingMemory | None:
        if not self.path.exists():
            return None
        return self.load()
