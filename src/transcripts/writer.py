"""Transcript persistence interfaces and local JSONL implementation."""

from __future__ import annotations

import os
from json import JSONDecodeError
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from transcripts.models import TranscriptEvent, parse_event, serialize_event


class TranscriptStoreError(ValueError):
    """Base error for transcript persistence failures."""


class TranscriptLoadError(TranscriptStoreError):
    """Raised when a transcript cannot be loaded safely."""


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
            handle.write(f"{serialize_event(event)}\n")
            handle.flush()
            os.fsync(handle.fileno())

    def read_all(self) -> tuple[TranscriptEvent, ...]:
        if not self.path.exists():
            return ()

        events: list[TranscriptEvent] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        events.append(parse_event(stripped))
                    except (JSONDecodeError, ValidationError) as exc:
                        msg = (
                            f"invalid transcript event in {self.path} at line "
                            f"{line_number}: {exc}"
                        )
                        raise TranscriptLoadError(msg) from exc
        except FileNotFoundError:
            raise
        return tuple(events)
