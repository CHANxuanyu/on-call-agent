"""Interactive operator shell for the narrow on-call runtime."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from context.handoff_regeneration import (
    HandoffArtifactRegenerationStatus,
    IncidentHandoffArtifactRegenerator,
)
from context.session_artifacts import SessionArtifactContext
from memory.checkpoints import (
    ApprovalStatus,
    JsonCheckpointStore,
    OperatorAutonomyMode,
    OperatorShellState,
)
from runtime.demo_target import DemoServiceDeploymentResponse
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
from runtime.settings import RuntimeSettings, load_runtime_settings
from tools.implementations.deployment_outcome_probe import DeploymentOutcomeProbeOutput
from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.incident_action_stub import ActionCandidateType
from tools.implementations.incident_hypothesis import (
    DEPLOYMENT_REGRESSION_VALIDATION_GAP,
    HypothesisType,
)
from tools.implementations.incident_recommendation import RecommendationType
from transcripts.models import CheckpointWrittenEvent, TranscriptEventType, VerifierResultEvent
from transcripts.writer import JsonlTranscriptStore


class AutoSafeGateResult(BaseModel):
    """Outcome of the narrow auto-safe rollback gate."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str = Field(min_length=1)
    checked_conditions: list[str] = Field(default_factory=list)


def derived_working_memory_root(checkpoint_root: Path) -> Path:
    """Return the working-memory root paired with the checkpoint root."""

    return checkpoint_root.parent / "working_memory"


def build_shell_status_payload(
    artifact_context: SessionArtifactContext,
) -> dict[str, str | int | bool | None]:
    """Build a compact operator-facing status payload."""

    checkpoint = artifact_context.checkpoint
    operator_shell = checkpoint.operator_shell
    approval_state = checkpoint.approval_state
    latest_verifier = _latest_verifier_summary(artifact_context)
    return {
        "session_id": artifact_context.session_id,
        "incident_id": checkpoint.incident_id,
        "current_phase": checkpoint.current_phase,
        "current_step": checkpoint.current_step,
        "requested_mode": operator_shell.requested_mode.value,
        "effective_mode": operator_shell.effective_mode.value,
        "mode_reason": operator_shell.mode_reason,
        "approval_status": approval_state.status.value,
        "approval_requested_action": approval_state.requested_action,
        "next_action": _next_action_summary(artifact_context),
        "current_evidence_summary": _current_evidence_summary(artifact_context),
        "latest_verifier": latest_verifier,
    }


def render_shell_status_payload(payload: dict[str, str | int | bool | None]) -> str:
    """Render the compact operator shell status view."""

    lines = [
        f"session: {payload['session_id']} incident={payload['incident_id']}",
        f"mode: requested={payload['requested_mode']} effective={payload['effective_mode']}",
        f"phase: {payload['current_phase']} step={payload['current_step']}",
        "approval: "
        f"{payload['approval_status']}"
        + (
            f" ({payload['approval_requested_action']})"
            if payload["approval_requested_action"] is not None
            else ""
        ),
        f"next: {payload['next_action']}",
        f"evidence: {payload['current_evidence_summary']}",
        f"verifier: {payload['latest_verifier']}",
    ]
    if payload["mode_reason"] is not None:
        lines.insert(2, f"mode_reason: {payload['mode_reason']}")
    return "\n".join(lines)


def _current_evidence_summary(artifact_context: SessionArtifactContext) -> str:
    outcome_probe = artifact_context.latest_verified_outcome_verification_output().artifact
    if outcome_probe is not None:
        return outcome_probe.summary

    evidence_output = artifact_context.latest_verified_evidence_output().artifact
    if evidence_output is not None:
        return evidence_output.evidence_summary

    latest_evidence_output = artifact_context.latest_evidence_output().output
    if isinstance(latest_evidence_output, EvidenceReadOutput):
        return latest_evidence_output.evidence_summary

    working_memory = artifact_context.latest_incident_working_memory()
    if working_memory is not None:
        return working_memory.compact_handoff_note
    return "No verifier-backed evidence summary is available yet."


def _latest_verifier_summary(artifact_context: SessionArtifactContext) -> str:
    for event in reversed(artifact_context.transcript_events):
        if isinstance(event, VerifierResultEvent):
            return (
                f"{event.verifier_name}={event.result.status.value}: "
                f"{event.result.summary}"
            )
    return "No verifier result has been recorded yet."


def _next_action_summary(artifact_context: SessionArtifactContext) -> str:
    checkpoint = artifact_context.checkpoint
    if (
        checkpoint.current_phase == "action_stub_pending_approval"
        and checkpoint.approval_state.status is ApprovalStatus.PENDING
    ):
        return "Review the rollback candidate and run /approve or /deny."
    if checkpoint.current_phase == "action_stub_denied":
        return "Inspect the artifacts and decide whether further read-only investigation is needed."
    if checkpoint.current_phase == "action_execution_completed":
        return "Run /verify to confirm post-rollback recovery."
    if checkpoint.current_phase == "outcome_verification_succeeded":
        return "Export handoff or continue monitoring the recovered service."

    action_stub = artifact_context.latest_verified_action_stub_output().artifact
    if action_stub is not None:
        return action_stub.action_summary

    recommendation = artifact_context.latest_verified_recommendation_output().artifact
    if recommendation is not None:
        return recommendation.action_summary

    return "Inspect the session and continue from the latest stable checkpoint."


@dataclass(slots=True)
class OperatorShell:
    """Simple line-oriented shell over the existing operator runtime seams."""

    checkpoint_root: Path = Path("sessions/checkpoints")
    transcript_root: Path = Path("sessions/transcripts")
    handoff_root: Path = Path("sessions/handoffs")
    settings_path: Path = Path(".oncall/settings.toml")
    skills_root: Path = Path("skills")
    initial_mode: OperatorAutonomyMode | None = None
    input_func: Callable[[str], str] = input
    stdout: TextIO = sys.stdout
    stderr: TextIO = sys.stderr
    settings: RuntimeSettings = field(init=False)
    current_session_id: str | None = field(init=False, default=None)
    requested_mode: OperatorAutonomyMode = field(init=False)
    effective_mode: OperatorAutonomyMode = field(init=False)
    mode_reason: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.settings = load_runtime_settings(self.settings_path)
        default_mode = self.initial_mode or self.settings.shell.default_mode
        self.requested_mode = default_mode
        self.effective_mode = default_mode

    @property
    def working_memory_root(self) -> Path:
        return derived_working_memory_root(self.checkpoint_root)

    def run(self) -> int:
        self._write("oncall-agent shell ready. Use /help for commands.")
        while True:
            try:
                line = self.input_func(self._prompt())
            except EOFError:
                self._write("Exiting shell.")
                return 0

            should_exit = self.handle_line(line)
            if should_exit:
                return 0

    def handle_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False

        try:
            parts = shlex.split(stripped)
        except ValueError as exc:
            self._error(str(exc))
            return False

        command = parts[0].lstrip("/").lower()
        arguments = parts[1:]

        try:
            if command in {"help", "h", "?"}:
                self._write(self._help_text())
                return False
            if command == "mode":
                self._handle_mode(arguments)
                return False
            if command == "new":
                self._handle_new(arguments)
                return False
            if command == "resume":
                self._handle_resume(arguments)
                return False
            if command == "status":
                self._handle_status(arguments)
                return False
            if command == "inspect":
                self._handle_inspect(arguments)
                return False
            if command == "audit":
                self._handle_audit(arguments)
                return False
            if command == "approve":
                self._handle_approval("approve", arguments)
                return False
            if command == "deny":
                self._handle_approval("deny", arguments)
                return False
            if command == "verify":
                self._handle_verify(arguments)
                return False
            if command == "handoff":
                self._handle_handoff(arguments)
                return False
            if command in {"exit", "quit"}:
                return True
        except (FileNotFoundError, OSError, ValueError, ValidationError, httpx.HTTPError) as exc:
            self._error(str(exc))
            return False

        self._error(f"unknown command: {command}. Use /help.")
        return False

    def _handle_mode(self, arguments: list[str]) -> None:
        if not arguments:
            self._write(self._current_mode_text())
            return
        if len(arguments) != 1:
            raise ValueError("/mode takes exactly one mode: manual, semi-auto, or auto-safe")

        requested_mode = OperatorAutonomyMode(arguments[0])
        self.requested_mode = requested_mode
        self.effective_mode = requested_mode
        self.mode_reason = None

        if self.current_session_id is None:
            self._write(self._current_mode_text())
            return

        self._write_operator_shell_state(
            session_id=self.current_session_id,
            requested_mode=requested_mode,
            effective_mode=requested_mode,
            reason=None,
        )
        context = self._load_context(self.current_session_id)
        self._sync_from_context(context)
        context = self._maybe_auto_progress(context)
        self._sync_from_context(context)
        self._write(render_shell_status_payload(build_shell_status_payload(context)))

    def _handle_new(self, arguments: list[str]) -> None:
        payload_path, force_new_session = self._parse_new_arguments(arguments)
        operator_shell = OperatorShellState(
            requested_mode=self.requested_mode,
            effective_mode=self.requested_mode,
        )
        payload = run_start_deployment_regression_incident(
            payload_path=payload_path,
            skills_root=self.skills_root,
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            operator_shell=operator_shell,
            force_new_session=force_new_session,
        )
        session_id = str(payload["session_id"])
        self.current_session_id = session_id
        if force_new_session:
            self._write(f"created new session: {session_id}")
        else:
            self._write(f"reused payload session: {session_id}")
        context = self._load_context(session_id)
        self._sync_from_context(context)
        context = self._maybe_auto_progress(context)
        self._sync_from_context(context)
        self._write(render_shell_status_payload(build_shell_status_payload(context)))

    def _handle_resume(self, arguments: list[str]) -> None:
        if len(arguments) != 1:
            raise ValueError("/resume requires exactly one session id")
        session_id = arguments[0]
        context = self._load_context(session_id)
        self.current_session_id = session_id
        self._sync_from_context(context)
        context = self._maybe_auto_progress(context)
        self._sync_from_context(context)
        self._write(render_shell_status_payload(build_shell_status_payload(context)))

    def _handle_status(self, arguments: list[str]) -> None:
        if arguments:
            raise ValueError("/status does not take arguments")
        context = self._require_current_context()
        self._write(render_shell_status_payload(build_shell_status_payload(context)))

    def _handle_inspect(self, arguments: list[str]) -> None:
        subject = arguments[0] if arguments else "artifacts"
        context = self._require_current_context()
        if subject == "session":
            payload = build_session_payload(context)
            self._write(render_session_payload(payload))
            return
        if subject == "artifacts":
            payload = build_artifact_payload(context)
            self._write(render_artifact_payload(payload))
            return
        raise ValueError("/inspect accepts either 'session' or 'artifacts'")

    def _handle_audit(self, arguments: list[str]) -> None:
        limit: int | None = None
        event_type: TranscriptEventType | None = None
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument == "--limit":
                index += 1
                if index >= len(arguments):
                    raise ValueError("/audit --limit requires an integer value")
                limit = int(arguments[index])
            elif argument == "--event-type":
                index += 1
                if index >= len(arguments):
                    raise ValueError("/audit --event-type requires a value")
                event_type = TranscriptEventType(arguments[index])
            else:
                raise ValueError(f"unknown /audit argument: {argument}")
            index += 1

        context = self._require_current_context()
        events = filter_audit_events(context, limit=limit, event_type=event_type)
        payload = build_audit_payload(
            context,
            events=events,
            limit=limit,
            event_type=event_type,
        )
        self._write(render_audit_events(events))
        if not events:
            self._write("No audit events matched the current filters.")
        elif payload["applied_filters"]["event_type"] is not None or limit is not None:
            self._write(
                "Applied filters: "
                f"event_type={payload['applied_filters']['event_type'] or 'all'} "
                f"limit={payload['applied_filters']['limit'] or 'none'}"
            )

    def _handle_approval(self, decision: str, arguments: list[str]) -> None:
        context = self._require_current_context()
        default_reason = (
            "Approved from the operator shell."
            if decision == "approve"
            else "Denied from the operator shell."
        )
        reason = " ".join(arguments).strip() or default_reason
        run_resolve_deployment_regression_approval(
            session_id=context.session_id,
            decision=decision,
            reason=reason,
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
        )
        refreshed = self._load_context(context.session_id)
        self._sync_from_context(refreshed)
        self._write(render_shell_status_payload(build_shell_status_payload(refreshed)))

    def _handle_verify(self, arguments: list[str]) -> None:
        if arguments:
            raise ValueError("/verify does not take arguments")
        context = self._require_current_context()
        run_verify_deployment_regression_outcome(
            session_id=context.session_id,
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
        )
        refreshed = self._load_context(context.session_id)
        self._sync_from_context(refreshed)
        self._write(render_shell_status_payload(build_shell_status_payload(refreshed)))

    def _handle_handoff(self, arguments: list[str]) -> None:
        if arguments:
            raise ValueError("/handoff does not take arguments")
        context = self._require_current_context()
        regenerator = IncidentHandoffArtifactRegenerator(
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            working_memory_root=self.working_memory_root,
            handoff_root=self.handoff_root,
        )
        result = regenerator.regenerate(context.session_id)
        payload = build_export_payload(result)
        self._write(render_export_payload(payload))
        if result.status is HandoffArtifactRegenerationStatus.INSUFFICIENT:
            self._write("Handoff export is blocked on currently insufficient verified artifacts.")

    def _maybe_auto_progress(
        self,
        artifact_context: SessionArtifactContext,
    ) -> SessionArtifactContext:
        checkpoint = artifact_context.checkpoint
        if checkpoint.operator_shell.effective_mode is not OperatorAutonomyMode.AUTO_SAFE:
            return artifact_context
        if checkpoint.current_phase != "action_stub_pending_approval":
            return artifact_context
        if checkpoint.approval_state.status is not ApprovalStatus.PENDING:
            return artifact_context

        gate = self.evaluate_auto_safe_gate(artifact_context)
        if not gate.allowed:
            self._write_operator_shell_state(
                session_id=artifact_context.session_id,
                requested_mode=OperatorAutonomyMode.AUTO_SAFE,
                effective_mode=OperatorAutonomyMode.SEMI_AUTO,
                reason=gate.reason,
            )
            self._write(f"auto-safe degraded to semi-auto: {gate.reason}")
            return self._load_context(artifact_context.session_id)

        run_resolve_deployment_regression_approval(
            session_id=artifact_context.session_id,
            decision="approve",
            reason=(
                "Auto-safe policy approved the bounded rollback because the incident "
                "matched the configured deployment-regression rollback gate."
            ),
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
        )
        self._write("auto-safe approved and executed the bounded rollback.")
        return self._load_context(artifact_context.session_id)

    def evaluate_auto_safe_gate(
        self,
        artifact_context: SessionArtifactContext,
    ) -> AutoSafeGateResult:
        checks: list[str] = []
        policy = self.settings.autonomy.auto_safe
        if not policy.enabled:
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    "auto-safe execution is disabled in the runtime settings, so the shell "
                    "must fail closed to semi-auto"
                ),
                checked_conditions=checks,
            )
        checks.append("auto-safe policy is enabled")

        if artifact_context.checkpoint.current_phase != "action_stub_pending_approval":
            return AutoSafeGateResult(
                allowed=False,
                reason="auto-safe only applies at the pending approval boundary",
                checked_conditions=checks,
            )
        checks.append("session is at the pending approval boundary")

        triage_input = artifact_context.latest_triage_input()
        if (
            triage_input is None
            or triage_input.service_base_url is None
            or triage_input.expected_bad_version is None
            or triage_input.expected_previous_version is None
        ):
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    "auto-safe requires the original live target and expected versions from "
                    "incident intake"
                ),
                checked_conditions=checks,
            )

        if triage_input.service_base_url not in policy.allowed_base_urls:
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    f"target {triage_input.service_base_url} is not allowlisted for "
                    "auto-safe execution"
                ),
                checked_conditions=checks,
            )
        checks.append("target base URL is allowlisted")

        hypothesis = artifact_context.latest_verified_hypothesis_output().artifact
        recommendation = artifact_context.latest_verified_recommendation_output().artifact
        action_stub = artifact_context.latest_verified_action_stub_output().artifact
        if hypothesis is None or recommendation is None or action_stub is None:
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    "auto-safe requires verified hypothesis, recommendation, and action stub "
                    "artifacts"
                ),
                checked_conditions=checks,
            )
        checks.append("verified hypothesis, recommendation, and action stub are present")

        if (
            hypothesis.hypothesis_type is not HypothesisType.DEPLOYMENT_REGRESSION
            or not hypothesis.evidence_supported
        ):
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    "auto-safe requires a strongly supported deployment-regression "
                    "hypothesis"
                ),
                checked_conditions=checks,
            )
        checks.append("deployment-regression hypothesis is verifier-backed and supported")

        if (
            recommendation.recommendation_type
            is not RecommendationType.VALIDATE_RECENT_DEPLOYMENT
        ):
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    "auto-safe requires the rollback-readiness recommendation branch for "
                    "recent deployment regression"
                ),
                checked_conditions=checks,
            )
        checks.append("recommendation matches rollback-readiness validation")

        if (
            action_stub.action_candidate_type
            is not ActionCandidateType.ROLLBACK_RECENT_DEPLOYMENT_CANDIDATE
            or not action_stub.action_candidate_created
        ):
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    "auto-safe requires the bounded rollback_recent_deployment_candidate"
                ),
                checked_conditions=checks,
            )
        checks.append("action stub is the bounded rollback candidate")

        working_memory = artifact_context.latest_incident_working_memory()
        if working_memory is None:
            return AutoSafeGateResult(
                allowed=False,
                reason="auto-safe requires current incident working memory",
                checked_conditions=checks,
            )

        blocking_gaps = [
            gap
            for gap in working_memory.unresolved_gaps
            if gap != DEPLOYMENT_REGRESSION_VALIDATION_GAP
        ]
        if blocking_gaps:
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    "auto-safe found unresolved blocking gaps: "
                    + "; ".join(blocking_gaps)
                ),
                checked_conditions=checks,
            )
        checks.append("no unresolved blocking gaps remain before rollback")

        try:
            with httpx.Client(timeout=5.0) as client:
                deployment_response = client.get(
                    f"{triage_input.service_base_url.rstrip('/')}/deployment"
                )
                deployment_response.raise_for_status()
            deployment = DemoServiceDeploymentResponse.model_validate(
                deployment_response.json()
            )
        except (httpx.HTTPError, ValidationError) as exc:
            return AutoSafeGateResult(
                allowed=False,
                reason=f"auto-safe could not confirm live deployment state: {exc}",
                checked_conditions=checks,
            )

        if deployment.current_version != triage_input.expected_bad_version:
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    "auto-safe refused because the live current version no longer matches "
                    f"the expected bad version {triage_input.expected_bad_version}"
                ),
                checked_conditions=checks,
            )
        checks.append("live current version matches the expected bad version")

        if deployment.previous_version != triage_input.expected_previous_version:
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    "auto-safe refused because the live previous version does not match "
                    f"the expected previous version {triage_input.expected_previous_version}"
                ),
                checked_conditions=checks,
            )
        checks.append("live previous version matches the expected known-good version")

        if (
            not deployment.recent_deployment
            or not deployment.bad_release_active
            or not deployment.rollback_available
        ):
            return AutoSafeGateResult(
                allowed=False,
                reason=(
                    "auto-safe refused because the live deployment endpoint no longer reports "
                    "a recent active bad release with rollback available"
                ),
                checked_conditions=checks,
            )
        checks.append("live deployment endpoint still reports a rollback-safe bad release")

        outcome_probe = artifact_context.latest_verified_outcome_verification_output().artifact
        if outcome_probe is not None and isinstance(outcome_probe, DeploymentOutcomeProbeOutput):
            return AutoSafeGateResult(
                allowed=False,
                reason="auto-safe is only valid before rollback execution has already completed",
                checked_conditions=checks,
            )
        checks.append("rollback has not already been executed")

        return AutoSafeGateResult(
            allowed=True,
            reason=(
                "all narrow auto-safe conditions passed for the allowlisted "
                "deployment-regression rollback path"
            ),
            checked_conditions=checks,
        )

    def _write_operator_shell_state(
        self,
        *,
        session_id: str,
        requested_mode: OperatorAutonomyMode,
        effective_mode: OperatorAutonomyMode,
        reason: str | None,
    ) -> None:
        artifact_context = self._load_context(session_id)
        existing = artifact_context.checkpoint.operator_shell
        if (
            existing.requested_mode is requested_mode
            and existing.effective_mode is effective_mode
            and existing.mode_reason == reason
        ):
            return

        operator_shell = OperatorShellState(
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            mode_reason=reason,
        )
        checkpoint = artifact_context.checkpoint.model_copy(
            update={
                "checkpoint_id": self._operator_checkpoint_id(session_id),
                "operator_shell": operator_shell,
                "latest_checkpoint_time": datetime.now(UTC),
                "summary_of_progress": self._mode_checkpoint_summary(
                    artifact_context.checkpoint.summary_of_progress,
                    requested_mode=requested_mode,
                    effective_mode=effective_mode,
                    reason=reason,
                ),
            },
            deep=True,
        )
        checkpoint_path = JsonCheckpointStore(artifact_context.checkpoint_path).write(checkpoint)
        JsonlTranscriptStore(artifact_context.transcript_path).append(
            CheckpointWrittenEvent(
                session_id=session_id,
                step_index=artifact_context.checkpoint.current_step,
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_path=checkpoint_path,
                summary_of_progress=checkpoint.summary_of_progress,
            )
        )

    def _operator_checkpoint_id(self, session_id: str) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        return f"{session_id}-operator-shell-{timestamp}"

    def _mode_checkpoint_summary(
        self,
        summary_of_progress: str,
        *,
        requested_mode: OperatorAutonomyMode,
        effective_mode: OperatorAutonomyMode,
        reason: str | None,
    ) -> str:
        base_summary = summary_of_progress
        marker = " Operator shell mode:"
        if marker in summary_of_progress:
            base_summary = summary_of_progress.split(marker, maxsplit=1)[0]

        mode_summary = (
            "Operator shell mode: "
            f"requested={requested_mode.value}, effective={effective_mode.value}."
        )
        if reason is not None:
            mode_summary = f"{mode_summary} Reason: {reason}"
        return f"{base_summary.strip()} {mode_summary}".strip()

    def _parse_new_arguments(self, arguments: list[str]) -> tuple[Path, bool]:
        if not arguments:
            raise ValueError("/new requires a payload path")
        force_new_session = True
        remaining = list(arguments)
        if "--reuse-payload-session" in remaining:
            remaining.remove("--reuse-payload-session")
            force_new_session = False
        if len(remaining) == 1:
            return Path(remaining[0]), force_new_session
        if len(remaining) == 2 and remaining[0] == "--payload":
            return Path(remaining[1]), force_new_session
        raise ValueError(
            "/new expects '/new <payload>', '/new --payload <payload>', or "
            "'/new --reuse-payload-session <payload>'"
        )

    def _require_current_context(self) -> SessionArtifactContext:
        if self.current_session_id is None:
            raise ValueError("no session is active; use /new or /resume first")
        return self._load_context(self.current_session_id)

    def _load_context(self, session_id: str) -> SessionArtifactContext:
        return load_artifact_context(
            session_id,
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            working_memory_root=self.working_memory_root,
        )

    def _sync_from_context(self, artifact_context: SessionArtifactContext) -> None:
        operator_shell = artifact_context.checkpoint.operator_shell
        self.requested_mode = operator_shell.requested_mode
        self.effective_mode = operator_shell.effective_mode
        self.mode_reason = operator_shell.mode_reason

    def _current_mode_text(self) -> str:
        reason_suffix = (
            f" reason={self.mode_reason}" if self.mode_reason is not None else ""
        )
        return (
            "mode: "
            f"requested={self.requested_mode.value} "
            f"effective={self.effective_mode.value}{reason_suffix}"
        )

    def _prompt(self) -> str:
        mode = (
            self.requested_mode.value
            if self.requested_mode is self.effective_mode
            else f"{self.requested_mode.value}->{self.effective_mode.value}"
        )
        session_label = self.current_session_id or "no-session"
        return f"oncall-agent[{mode}][{session_label}]> "

    def _help_text(self) -> str:
        return "\n".join(
            [
                "Commands:",
                "/help",
                "/mode [manual|semi-auto|auto-safe]",
                "/new <payload-path>",
                "/new --reuse-payload-session <payload-path>",
                "/resume <session-id>",
                "/status",
                "/inspect [session|artifacts]",
                "/audit [--event-type <type>] [--limit <n>]",
                "/approve [reason]",
                "/deny [reason]",
                "/verify",
                "/handoff",
                "/exit",
            ]
        )

    def _write(self, message: str) -> None:
        print(message, file=self.stdout)

    def _error(self, message: str) -> None:
        print(f"error: {message}", file=self.stderr)
