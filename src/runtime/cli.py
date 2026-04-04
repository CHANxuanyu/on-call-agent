"""Thin operator CLI for read-only session inspection and handoff export."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from json import JSONDecodeError
from pathlib import Path

from pydantic import ValidationError

from context.handoff_regeneration import (
    HandoffArtifactRegenerationStatus,
    IncidentHandoffArtifactRegenerator,
)
from runtime.inspect import (
    build_artifact_payload,
    build_audit_payload,
    build_export_payload,
    build_session_payload,
    filter_audit_events,
    load_artifact_context,
    render_artifact_payload,
    render_audit_events,
    render_export_payload,
    render_session_payload,
)
from transcripts.models import TranscriptEventType


def main(argv: Sequence[str] | None = None) -> int:
    """Run the thin inspection/export CLI."""

    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "inspect-session":
        return _run_inspect_session(args)
    if args.command == "inspect-artifacts":
        return _run_inspect_artifacts(args)
    if args.command == "show-audit":
        return _run_show_audit(args)
    if args.command == "export-handoff":
        return _run_export_handoff(args)

    parser.error(f"unknown command: {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oncall-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_session = subparsers.add_parser("inspect-session")
    inspect_session.add_argument("session_id")
    _add_shared_session_arguments(inspect_session)

    inspect_artifacts = subparsers.add_parser("inspect-artifacts")
    inspect_artifacts.add_argument("session_id")
    _add_shared_session_arguments(inspect_artifacts)

    show_audit = subparsers.add_parser("show-audit")
    show_audit.add_argument("session_id")
    _add_shared_session_arguments(show_audit)
    show_audit.add_argument("--limit", type=int, default=None)
    show_audit.add_argument(
        "--event-type",
        choices=[event_type.value for event_type in TranscriptEventType],
        default=None,
    )

    export_handoff = subparsers.add_parser("export-handoff")
    export_handoff.add_argument("session_id")
    _add_shared_session_arguments(export_handoff, include_handoff_root=True)

    return parser


def _add_shared_session_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_handoff_root: bool = False,
) -> None:
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        default=Path("sessions/checkpoints"),
    )
    parser.add_argument(
        "--transcript-root",
        type=Path,
        default=Path("sessions/transcripts"),
    )
    parser.add_argument(
        "--working-memory-root",
        type=Path,
        default=None,
    )
    if include_handoff_root:
        parser.add_argument(
            "--handoff-root",
            type=Path,
            default=Path("sessions/handoffs"),
        )
    parser.add_argument("--json", action="store_true", dest="json_output")


def _run_inspect_session(args: argparse.Namespace) -> int:
    try:
        artifact_context = load_artifact_context(
            args.session_id,
            checkpoint_root=args.checkpoint_root,
            transcript_root=args.transcript_root,
            working_memory_root=args.working_memory_root,
        )
    except _inspect_errors() as exc:
        _print_error(str(exc))
        return 1

    payload = build_session_payload(artifact_context)
    _emit(payload, render_session_payload(payload), json_output=args.json_output)
    return 0


def _run_inspect_artifacts(args: argparse.Namespace) -> int:
    try:
        artifact_context = load_artifact_context(
            args.session_id,
            checkpoint_root=args.checkpoint_root,
            transcript_root=args.transcript_root,
            working_memory_root=args.working_memory_root,
        )
    except _inspect_errors() as exc:
        _print_error(str(exc))
        return 1

    payload = build_artifact_payload(artifact_context)
    _emit(payload, render_artifact_payload(payload), json_output=args.json_output)
    return 0


def _run_show_audit(args: argparse.Namespace) -> int:
    try:
        artifact_context = load_artifact_context(
            args.session_id,
            checkpoint_root=args.checkpoint_root,
            transcript_root=args.transcript_root,
            working_memory_root=args.working_memory_root,
        )
    except _inspect_errors() as exc:
        _print_error(str(exc))
        return 1

    event_type = (
        TranscriptEventType(args.event_type) if args.event_type is not None else None
    )
    events = filter_audit_events(
        artifact_context,
        limit=args.limit,
        event_type=event_type,
    )
    payload = build_audit_payload(
        artifact_context,
        events=events,
        limit=args.limit,
        event_type=event_type,
    )
    _emit(payload, render_audit_events(events), json_output=args.json_output)
    return 0


def _run_export_handoff(args: argparse.Namespace) -> int:
    regenerator = IncidentHandoffArtifactRegenerator(
        checkpoint_root=args.checkpoint_root,
        transcript_root=args.transcript_root,
        working_memory_root=args.working_memory_root,
        handoff_root=args.handoff_root,
    )
    result = regenerator.regenerate(args.session_id)
    payload = build_export_payload(result)
    _emit(payload, render_export_payload(payload), json_output=args.json_output)
    if result.status is HandoffArtifactRegenerationStatus.WRITTEN:
        return 0
    if result.status is HandoffArtifactRegenerationStatus.INSUFFICIENT:
        return 2
    return 1


def _emit(payload: object, text: str, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(text)


def _print_error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


def _inspect_errors() -> tuple[type[BaseException], ...]:
    return (FileNotFoundError, JSONDecodeError, ValidationError, ValueError, OSError)


if __name__ == "__main__":
    raise SystemExit(main())
