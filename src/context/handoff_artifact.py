"""Stable operator-facing handoff artifact persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from context.handoff import IncidentHandoffContext
from context.session_artifacts import SessionArtifactContext


class IncidentHandoffArtifact(BaseModel):
    """Deterministic on-disk handoff artifact derived from runtime truth."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    source_session_id: str = Field(min_length=1)
    source_checkpoint_id: str = Field(min_length=1)
    source_checkpoint_time: datetime
    handoff: IncidentHandoffContext


def incident_handoff_artifact_path(
    incident_id: str,
    *,
    root: Path = Path("sessions/handoffs"),
) -> Path:
    """Return the deterministic handoff artifact path for one incident."""

    safe_incident_id = incident_id.replace("/", "__").replace("\\", "__")
    return root / f"{safe_incident_id}.json"


class JsonIncidentHandoffArtifactStore:
    """Simple local JSON store for handoff artifacts."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_incident(
        cls,
        incident_id: str,
        *,
        root: Path = Path("sessions/handoffs"),
    ) -> JsonIncidentHandoffArtifactStore:
        return cls(incident_handoff_artifact_path(incident_id, root=root))

    def write(self, artifact: IncidentHandoffArtifact) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self.path

    def load(self) -> IncidentHandoffArtifact:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return IncidentHandoffArtifact.model_validate(payload)

    def load_optional(self) -> IncidentHandoffArtifact | None:
        if not self.path.exists():
            return None
        return self.load()


@dataclass(slots=True)
class IncidentHandoffArtifactWriter:
    """Write a stable handoff artifact from an assembled handoff context."""

    root: Path = Path("sessions/handoffs")

    def build_artifact(
        self,
        *,
        artifact_context: SessionArtifactContext,
        handoff_context: IncidentHandoffContext,
    ) -> IncidentHandoffArtifact:
        return IncidentHandoffArtifact(
            source_session_id=artifact_context.session_id,
            source_checkpoint_id=artifact_context.checkpoint.checkpoint_id,
            source_checkpoint_time=artifact_context.checkpoint.latest_checkpoint_time,
            handoff=handoff_context,
        )

    def write(
        self,
        *,
        artifact_context: SessionArtifactContext,
        handoff_context: IncidentHandoffContext,
    ) -> Path:
        artifact = self.build_artifact(
            artifact_context=artifact_context,
            handoff_context=handoff_context,
        )
        return JsonIncidentHandoffArtifactStore.for_incident(
            artifact_context.checkpoint.incident_id,
            root=self.root,
        ).write(artifact)
