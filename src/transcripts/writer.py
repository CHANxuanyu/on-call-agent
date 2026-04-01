"""Transcript persistence interfaces and local JSONL implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from transcripts.models import TranscriptEvent, parse_event, serialize_event


class TranscriptWriter(Protocol):
    """Persists structured transcript events to durable storage."""

    def append(self, event: TranscriptEvent) -> None:
        """Persist one transcript event."""


class JsonlTranscriptStore:
    """Append-only JSONL transcript store on the local filesystem."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: TranscriptEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(serialize_event(event))
            handle.write("\n")

    def read_all(self) -> tuple[TranscriptEvent, ...]:
        if not self.path.exists():
            return ()

        events: list[TranscriptEvent] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    events.append(parse_event(stripped))
        return tuple(events)
