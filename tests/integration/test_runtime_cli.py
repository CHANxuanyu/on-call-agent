import json
from pathlib import Path

import pytest

from agent.incident_action_stub import (
    IncidentActionStubStep,
    IncidentActionStubStepRequest,
)
from agent.incident_evidence import IncidentEvidenceStep, IncidentEvidenceStepRequest
from agent.incident_follow_up import IncidentFollowUpStep, IncidentFollowUpStepRequest
from agent.incident_hypothesis import IncidentHypothesisStep, IncidentHypothesisStepRequest
from agent.incident_recommendation import (
    IncidentRecommendationStep,
    IncidentRecommendationStepRequest,
)
from agent.incident_triage import IncidentTriageStep, IncidentTriageStepRequest
from runtime.cli import main


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


async def _run_chain_to_action_stub(
    tmp_path: Path,
    *,
    session_id: str,
    incident_id: str,
) -> None:
    repo_root = _repository_root()
    triage_step = IncidentTriageStep(
        skills_root=repo_root / "skills",
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await triage_step.run(
        IncidentTriageStepRequest(
            session_id=session_id,
            incident_id=incident_id,
            title="Elevated 5xx errors on payments-api",
            service="payments-api",
            symptoms=["spike in 5xx", "checkout requests timing out"],
            impact_summary="Customer checkout requests are failing intermittently.",
            recent_deployment="deployment-2026-04-01",
        )
    )

    follow_up_step = IncidentFollowUpStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await follow_up_step.run(IncidentFollowUpStepRequest(session_id=session_id))

    evidence_step = IncidentEvidenceStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    evidence_step.tool.fixtures_path = repo_root / "evals/fixtures/evidence_snapshots.json"
    await evidence_step.run(IncidentEvidenceStepRequest(session_id=session_id))

    hypothesis_step = IncidentHypothesisStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await hypothesis_step.run(IncidentHypothesisStepRequest(session_id=session_id))

    recommendation_step = IncidentRecommendationStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await recommendation_step.run(IncidentRecommendationStepRequest(session_id=session_id))

    action_stub_step = IncidentActionStubStep(
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
    )
    await action_stub_step.run(IncidentActionStubStepRequest(session_id=session_id))


def _command_roots(tmp_path: Path) -> list[str]:
    return [
        "--checkpoint-root",
        str(tmp_path / "checkpoints"),
        "--transcript-root",
        str(tmp_path / "transcripts"),
        "--working-memory-root",
        str(tmp_path / "working_memory"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", ["inspect-session", "inspect-artifacts", "show-audit"])
async def test_inspect_commands_are_read_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command_name: str,
) -> None:
    session_id = "session-runtime-cli-read-only"
    incident_id = "incident-runtime-cli-read-only"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    checkpoint_path = tmp_path / "checkpoints" / f"{session_id}.json"
    transcript_path = tmp_path / "transcripts" / f"{session_id}.jsonl"
    working_memory_path = tmp_path / "working_memory" / f"{incident_id}.json"
    checkpoint_before = checkpoint_path.read_text(encoding="utf-8")
    transcript_before = transcript_path.read_text(encoding="utf-8")
    working_memory_before = working_memory_path.read_text(encoding="utf-8")

    argv = [command_name, session_id, *_command_roots(tmp_path)]
    if command_name == "show-audit":
        argv.extend(["--limit", "5", "--event-type", "verifier_result"])
    else:
        argv.append("--json")

    exit_code = main(argv)

    assert exit_code == 0
    assert checkpoint_path.read_text(encoding="utf-8") == checkpoint_before
    assert transcript_path.read_text(encoding="utf-8") == transcript_before
    assert working_memory_path.read_text(encoding="utf-8") == working_memory_before
    captured = capsys.readouterr()
    assert captured.out != ""
    assert captured.err == ""


@pytest.mark.asyncio
async def test_inspect_artifacts_json_returns_all_stages_in_fixed_order(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id = "session-runtime-cli-artifacts"
    incident_id = "incident-runtime-cli-artifacts"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    exit_code = main(
        ["inspect-artifacts", session_id, *_command_roots(tmp_path), "--json"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [stage["stage"] for stage in payload["stages"]] == [
        "triage",
        "follow_up",
        "evidence",
        "hypothesis",
        "recommendation",
        "action_stub",
        "action_execution",
        "outcome_verification",
    ]


@pytest.mark.asyncio
async def test_show_audit_json_filters_events(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id = "session-runtime-cli-audit"
    incident_id = "incident-runtime-cli-audit"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    exit_code = main(
        [
            "show-audit",
            session_id,
            *_command_roots(tmp_path),
            "--event-type",
            "verifier_result",
            "--limit",
            "2",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["event_count"] == 2
    assert all(event["event_type"] == "verifier_result" for event in payload["events"])


@pytest.mark.asyncio
async def test_export_handoff_writes_only_handoff_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id = "session-runtime-cli-export"
    incident_id = "incident-runtime-cli-export"
    await _run_chain_to_action_stub(
        tmp_path,
        session_id=session_id,
        incident_id=incident_id,
    )

    checkpoint_path = tmp_path / "checkpoints" / f"{session_id}.json"
    transcript_path = tmp_path / "transcripts" / f"{session_id}.jsonl"
    working_memory_path = tmp_path / "working_memory" / f"{incident_id}.json"
    checkpoint_before = checkpoint_path.read_text(encoding="utf-8")
    transcript_before = transcript_path.read_text(encoding="utf-8")
    working_memory_before = working_memory_path.read_text(encoding="utf-8")
    handoff_root = tmp_path / "handoffs"

    exit_code = main(
        [
            "export-handoff",
            session_id,
            *_command_roots(tmp_path),
            "--handoff-root",
            str(handoff_root),
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    handoff_files = list(handoff_root.glob("*.json"))
    assert payload["status"] == "written"
    assert payload["handoff_path"] == str(handoff_root / f"{incident_id}.json")
    assert handoff_files == [handoff_root / f"{incident_id}.json"]
    assert checkpoint_path.read_text(encoding="utf-8") == checkpoint_before
    assert transcript_path.read_text(encoding="utf-8") == transcript_before
    assert working_memory_path.read_text(encoding="utf-8") == working_memory_before
