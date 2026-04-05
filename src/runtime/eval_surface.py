"""Thin operator-facing surface for replay/eval discovery and summaries."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

from context.handoff_regeneration import (
    HandoffArtifactRegenerationResult,
    HandoffArtifactRegenerationStatus,
    IncidentHandoffArtifactRegenerator,
)
from context.session_artifacts import SessionArtifactContext
from evals.incident_chain_replay import (
    IncidentChainReplayExecution,
    IncidentChainReplayRunner,
    default_incident_chain_replay_scenarios,
    incident_chain_replay_scenario_by_id,
)
from evals.models import EvalScenario
from runtime.inspect import build_artifact_payload, load_artifact_context


class EvalPathClassification(StrEnum):
    """Compact operator-facing path classes for replay summaries."""

    SUPPORTED = "supported"
    CONSERVATIVE = "conservative"
    FAILURE_RECOVERY = "failure_recovery"
    UNKNOWN = "unknown"


def list_eval_scenarios(
    *,
    fixtures_root: Path = Path("evals/fixtures"),
) -> tuple[EvalScenario, ...]:
    """Return the built-in replay scenarios in stable display order."""

    return default_incident_chain_replay_scenarios(fixtures_root=fixtures_root)


def build_eval_list_payload(scenarios: tuple[EvalScenario, ...]) -> dict[str, Any]:
    """Build a stable machine-readable list of supported replay scenarios."""

    return {
        "scenario_count": len(scenarios),
        "scenarios": [
            {
                "name": scenario.scenario_id,
                "description": scenario.description,
                "fixture_path": str(scenario.fixture_path)
                if scenario.fixture_path is not None
                else None,
            }
            for scenario in scenarios
        ],
    }


def render_eval_list_payload(payload: dict[str, Any]) -> str:
    """Render a compact human-readable scenario list."""

    lines = [f"scenario_count: {payload['scenario_count']}"]
    for scenario in payload["scenarios"]:
        lines.append(f"{scenario['name']}: {scenario['description']}")
    return "\n".join(lines)


async def run_eval_scenario(
    scenario_name: str,
    *,
    fixtures_root: Path = Path("evals/fixtures"),
    skills_root: Path = Path("skills"),
    evidence_fixtures_path: Path = Path("evals/fixtures/evidence_snapshots.json"),
    output_root: Path = Path("sessions/evals"),
) -> dict[str, Any] | None:
    """Run one built-in replay scenario and summarize the resulting artifacts."""

    scenario = incident_chain_replay_scenario_by_id(
        scenario_name,
        fixtures_root=fixtures_root,
    )
    if scenario is None:
        return None

    output_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(mkdtemp(prefix=f"{scenario.scenario_id}-", dir=output_root))
    runner = IncidentChainReplayRunner(
        skills_root=skills_root,
        evidence_fixtures_path=evidence_fixtures_path,
    )
    execution = await runner.run_with_artifacts(scenario, artifacts_root=run_root)
    artifact_context = load_artifact_context(
        execution.session_id,
        checkpoint_root=execution.checkpoint_root,
        transcript_root=execution.transcript_root,
        working_memory_root=execution.working_memory_root,
    )
    handoff_result = IncidentHandoffArtifactRegenerator(
        checkpoint_root=execution.checkpoint_root,
        transcript_root=execution.transcript_root,
        working_memory_root=execution.working_memory_root,
        handoff_root=execution.artifacts_root / "handoffs",
    ).regenerate(execution.session_id)
    return build_eval_run_payload(
        execution=execution,
        artifact_context=artifact_context,
        handoff_result=handoff_result,
    )


def build_eval_run_payload(
    *,
    execution: IncidentChainReplayExecution,
    artifact_context: SessionArtifactContext,
    handoff_result: HandoffArtifactRegenerationResult,
) -> dict[str, Any]:
    """Build a compact structured replay summary from current durable artifacts."""

    artifact_payload = build_artifact_payload(artifact_context)
    stages = _build_stage_summaries(artifact_payload)
    return {
        "scenario_id": execution.scenario.scenario_id,
        "description": execution.scenario.description,
        "success": execution.result.success,
        "verifier_pass_rate": execution.result.verifier_pass_rate,
        "notes": list(execution.result.notes),
        "session_id": execution.session_id,
        "incident_id": artifact_context.checkpoint.incident_id,
        "output_root": str(execution.artifacts_root),
        "checkpoint_path": str(artifact_context.checkpoint_path),
        "transcript_path": str(artifact_context.transcript_path),
        "working_memory_path": str(artifact_context.working_memory_path),
        "current_phase": artifact_context.checkpoint.current_phase,
        "final_stage": _final_stage(artifact_context.checkpoint.current_phase),
        "path_classification": _classify_path(
            artifact_context=artifact_context,
            stages=stages,
        ).value,
        "handoff_status": handoff_result.status.value,
        "handoff_path": (
            str(handoff_result.handoff_path)
            if handoff_result.handoff_path is not None
            else None
        ),
        "handoff_available": (
            handoff_result.status is HandoffArtifactRegenerationStatus.WRITTEN
        ),
        "signals": _collect_notable_signals(
            stages=stages,
            handoff_result=handoff_result,
        ),
        "stages": stages,
    }


def render_eval_run_payload(payload: dict[str, Any]) -> str:
    """Render a compact operator-facing replay summary."""

    lines = [
        f"scenario_id: {payload['scenario_id']}",
        f"description: {payload['description']}",
        f"success: {payload['success']}",
        f"verifier_pass_rate: {payload['verifier_pass_rate']}",
        f"session_id: {payload['session_id']}",
        f"incident_id: {payload['incident_id']}",
        f"output_root: {payload['output_root']}",
        f"current_phase: {payload['current_phase']}",
        f"final_stage: {payload['final_stage']}",
        f"path_classification: {payload['path_classification']}",
        f"handoff_status: {payload['handoff_status']}",
        f"handoff_path: {payload['handoff_path'] or 'unavailable'}",
    ]
    if payload["signals"]:
        lines.append("signals:")
        for signal in payload["signals"]:
            lines.append(f"- {signal}")
    else:
        lines.append("signals: none")
    return "\n".join(lines)


def _build_stage_summaries(artifact_payload: dict[str, Any]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    for stage in artifact_payload["stages"]:
        record = stage["latest_record"]
        resolution = stage["verified_resolution"]
        state = "recorded"
        reason = None
        if resolution["is_available"]:
            state = "verified"
        elif resolution["is_failure"]:
            state = "failure"
            reason = resolution["reason"]
        elif resolution["is_insufficient"]:
            state = "insufficient"
            reason = resolution["reason"]
        elif record["invalid_output_detail"] is not None:
            state = "invalid_output"
            reason = record["invalid_output_detail"]
        elif record["has_output"]:
            state = "unverified"
        elif record["synthetic_failure"] is not None:
            state = "failure"
            reason = record["synthetic_failure"]["reason"]
        else:
            state = "missing"

        stages.append(
            {
                "stage": stage["stage"],
                "state": state,
                "verifier_status": record["verifier_status"],
                "reason": reason,
            }
        )
    return stages


def _final_stage(current_phase: str) -> str:
    if current_phase.startswith("action_stub"):
        return "action_stub"
    if current_phase.startswith("recommendation"):
        return "recommendation"
    if current_phase.startswith("hypothesis"):
        return "hypothesis"
    if current_phase.startswith("evidence"):
        return "evidence"
    if current_phase.startswith("follow_up"):
        return "follow_up"
    if current_phase.startswith("triage"):
        return "triage"
    return "unknown"


def _classify_path(
    *,
    artifact_context: SessionArtifactContext,
    stages: list[dict[str, Any]],
) -> EvalPathClassification:
    phase = artifact_context.checkpoint.current_phase

    if "failed_" in phase or any(stage["state"] == "failure" for stage in stages):
        return EvalPathClassification.FAILURE_RECOVERY
    if phase in {
        "hypothesis_insufficient_evidence",
        "recommendation_conservative",
        "action_stub_not_actionable",
    }:
        return EvalPathClassification.CONSERVATIVE
    if phase in {
        "recommendation_supported",
        "action_stub_pending_approval",
    }:
        return EvalPathClassification.SUPPORTED
    return EvalPathClassification.UNKNOWN


def _collect_notable_signals(
    *,
    stages: list[dict[str, Any]],
    handoff_result: HandoffArtifactRegenerationResult,
) -> list[str]:
    signals = [
        f"{stage['stage']}: {stage['state']} - {stage['reason']}"
        for stage in stages
        if stage["state"] in {"failure", "insufficient", "invalid_output"}
        and stage["reason"] is not None
    ]

    if handoff_result.status is HandoffArtifactRegenerationStatus.INSUFFICIENT:
        reason = handoff_result.insufficiency_reason or "handoff artifact unavailable"
        signals.append(f"handoff: insufficient - {reason}")
    elif handoff_result.status is HandoffArtifactRegenerationStatus.FAILED:
        reason = (
            handoff_result.artifact_failure.reason
            if handoff_result.artifact_failure is not None
            else "handoff artifact regeneration failed"
        )
        signals.append(f"handoff: failure - {reason}")

    return signals
