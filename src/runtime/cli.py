"""Operator CLI for inspection, replay, live flows, and the interactive shell."""

from __future__ import annotations

import argparse
import asyncio
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
from memory.checkpoints import OperatorAutonomyMode
from runtime.eval_surface import (
    build_eval_list_payload,
    list_eval_scenarios,
    render_eval_list_payload,
    render_eval_run_payload,
    run_eval_scenario,
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
from runtime.live_surface import (
    run_resolve_deployment_regression_approval,
    run_start_deployment_regression_incident,
    run_verify_deployment_regression_outcome,
)
from runtime.shell import OperatorShell
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
    if args.command == "list-evals":
        return _run_list_evals(args)
    if args.command == "run-eval":
        return _run_run_eval(args)
    if args.command == "start-incident":
        return _run_start_incident(args)
    if args.command == "resolve-approval":
        return _run_resolve_approval(args)
    if args.command == "verify-outcome":
        return _run_verify_outcome(args)
    if args.command == "run-demo-target":
        return _run_demo_target(args)
    if args.command == "shell":
        return _run_shell(args)

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

    list_evals = subparsers.add_parser("list-evals")
    list_evals.add_argument("--json", action="store_true", dest="json_output")

    run_eval = subparsers.add_parser("run-eval")
    run_eval.add_argument("eval_name")
    run_eval.add_argument(
        "--output-root",
        type=Path,
        default=Path("sessions/evals"),
    )
    run_eval.add_argument("--json", action="store_true", dest="json_output")

    start_incident = subparsers.add_parser("start-incident")
    start_incident.add_argument(
        "--family",
        choices=["deployment-regression"],
        required=True,
    )
    start_incident.add_argument("--payload", type=Path, required=True)
    start_incident.add_argument(
        "--checkpoint-root",
        type=Path,
        default=Path("sessions/checkpoints"),
    )
    start_incident.add_argument(
        "--transcript-root",
        type=Path,
        default=Path("sessions/transcripts"),
    )
    start_incident.add_argument("--json", action="store_true", dest="json_output")

    resolve_approval = subparsers.add_parser("resolve-approval")
    resolve_approval.add_argument("session_id")
    resolve_approval.add_argument(
        "--decision",
        choices=["approve", "deny"],
        required=True,
    )
    resolve_approval.add_argument("--reason", default=None)
    resolve_approval.add_argument(
        "--checkpoint-root",
        type=Path,
        default=Path("sessions/checkpoints"),
    )
    resolve_approval.add_argument(
        "--transcript-root",
        type=Path,
        default=Path("sessions/transcripts"),
    )
    resolve_approval.add_argument("--json", action="store_true", dest="json_output")

    verify_outcome = subparsers.add_parser("verify-outcome")
    verify_outcome.add_argument("session_id")
    verify_outcome.add_argument(
        "--checkpoint-root",
        type=Path,
        default=Path("sessions/checkpoints"),
    )
    verify_outcome.add_argument(
        "--transcript-root",
        type=Path,
        default=Path("sessions/transcripts"),
    )
    verify_outcome.add_argument("--json", action="store_true", dest="json_output")

    run_demo_target = subparsers.add_parser("run-demo-target")
    run_demo_target.add_argument("--host", default="127.0.0.1")
    run_demo_target.add_argument("--port", type=int, default=8001)
    run_demo_target.add_argument("--service", default="payments-api")
    run_demo_target.add_argument("--bad-version", default="2.1.0")
    run_demo_target.add_argument("--previous-version", default="2.0.9")
    run_demo_target.add_argument("--json", action="store_true", dest="json_output")

    shell = subparsers.add_parser("shell")
    shell.add_argument(
        "--checkpoint-root",
        type=Path,
        default=Path("sessions/checkpoints"),
    )
    shell.add_argument(
        "--transcript-root",
        type=Path,
        default=Path("sessions/transcripts"),
    )
    shell.add_argument(
        "--handoff-root",
        type=Path,
        default=Path("sessions/handoffs"),
    )
    shell.add_argument(
        "--settings-path",
        type=Path,
        default=Path(".oncall/settings.toml"),
    )
    shell.add_argument(
        "--skills-root",
        type=Path,
        default=Path("skills"),
    )
    shell.add_argument(
        "--mode",
        choices=["manual", "semi-auto", "auto-safe"],
        default=None,
    )

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


def _run_list_evals(args: argparse.Namespace) -> int:
    scenarios = list_eval_scenarios()
    payload = build_eval_list_payload(scenarios)
    _emit(payload, render_eval_list_payload(payload), json_output=args.json_output)
    return 0


def _run_run_eval(args: argparse.Namespace) -> int:
    payload = asyncio.run(
        run_eval_scenario(
            args.eval_name,
            output_root=args.output_root,
        )
    )
    if payload is None:
        valid_names = ", ".join(scenario.scenario_id for scenario in list_eval_scenarios())
        _print_error(f"unknown eval: {args.eval_name}. valid names: {valid_names}")
        return 1
    _emit(payload, render_eval_run_payload(payload), json_output=args.json_output)
    return 0 if payload["success"] else 1


def _run_start_incident(args: argparse.Namespace) -> int:
    payload = run_start_deployment_regression_incident(
        payload_path=args.payload,
        checkpoint_root=args.checkpoint_root,
        transcript_root=args.transcript_root,
    )
    _emit(payload, render_session_payload(payload), json_output=args.json_output)
    return 0


def _run_resolve_approval(args: argparse.Namespace) -> int:
    payload = run_resolve_deployment_regression_approval(
        session_id=args.session_id,
        decision=args.decision,
        reason=args.reason,
        checkpoint_root=args.checkpoint_root,
        transcript_root=args.transcript_root,
    )
    _emit(payload, render_session_payload(payload), json_output=args.json_output)
    return 0


def _run_verify_outcome(args: argparse.Namespace) -> int:
    payload = run_verify_deployment_regression_outcome(
        session_id=args.session_id,
        checkpoint_root=args.checkpoint_root,
        transcript_root=args.transcript_root,
    )
    _emit(payload, render_session_payload(payload), json_output=args.json_output)
    return 0


def _run_demo_target(args: argparse.Namespace) -> int:
    from runtime.demo_target import DemoDeploymentTargetServer

    server = DemoDeploymentTargetServer(
        host=args.host,
        port=args.port,
        service=args.service,
        bad_version=args.bad_version,
        previous_version=args.previous_version,
    )
    payload = {
        "service": args.service,
        "base_url": server.base_url,
        "bad_version": args.bad_version,
        "previous_version": args.previous_version,
    }
    if args.json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"demo target ready at {server.base_url} for service {args.service}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.close()
    return 0


def _run_shell(args: argparse.Namespace) -> int:
    shell = OperatorShell(
        checkpoint_root=args.checkpoint_root,
        transcript_root=args.transcript_root,
        handoff_root=args.handoff_root,
        settings_path=args.settings_path,
        skills_root=args.skills_root,
        initial_mode=(
            OperatorAutonomyMode(args.mode) if args.mode is not None else None
        ),
    )
    return shell.run()


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
