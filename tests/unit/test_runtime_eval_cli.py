import json
from pathlib import Path

from evals.incident_chain_replay import incident_chain_replay_scenario_by_id
from evals.models import EvalScenario
from runtime.cli import main


def test_list_evals_json_returns_stable_payload(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "runtime.cli.list_eval_scenarios",
        lambda: (
            EvalScenario(
                scenario_id="scenario-a",
                description="Supported path replay.",
                fixture_path=Path("evals/fixtures/scenario-a.json"),
            ),
            EvalScenario(
                scenario_id="scenario-b",
                description="Conservative path replay.",
                fixture_path=Path("evals/fixtures/scenario-b.json"),
            ),
        ),
    )

    exit_code = main(["list-evals", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "scenario_count": 2,
        "scenarios": [
            {
                "description": "Supported path replay.",
                "fixture_path": "evals/fixtures/scenario-a.json",
                "name": "scenario-a",
            },
            {
                "description": "Conservative path replay.",
                "fixture_path": "evals/fixtures/scenario-b.json",
                "name": "scenario-b",
            },
        ],
    }


def test_run_eval_json_returns_payload_and_success_exit_code(
    monkeypatch,
    capsys,
) -> None:
    async def _fake_run_eval_scenario(
        scenario_name: str,
        *,
        output_root: Path,
    ) -> dict[str, object] | None:
        assert scenario_name == "scenario-a"
        assert output_root == Path("sessions/evals")
        return {
            "scenario_id": scenario_name,
            "description": "Supported path replay.",
            "success": True,
            "verifier_pass_rate": 1.0,
            "session_id": "scenario-a-session",
            "incident_id": "incident-a",
            "output_root": "sessions/evals/scenario-a-run",
            "checkpoint_path": "sessions/evals/scenario-a-run/checkpoints/scenario-a.json",
            "transcript_path": "sessions/evals/scenario-a-run/transcripts/scenario-a.jsonl",
            "working_memory_path": (
                "sessions/evals/scenario-a-run/working_memory/incident-a.json"
            ),
            "current_phase": "action_stub_pending_approval",
            "final_stage": "action_stub",
            "path_classification": "supported",
            "handoff_status": "written",
            "handoff_path": "sessions/evals/scenario-a-run/handoffs/incident-a.json",
            "handoff_available": True,
            "signals": [],
            "notes": [],
            "stages": [],
        }

    monkeypatch.setattr("runtime.cli.run_eval_scenario", _fake_run_eval_scenario)

    exit_code = main(["run-eval", "scenario-a", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scenario_id"] == "scenario-a"
    assert payload["path_classification"] == "supported"
    assert payload["handoff_available"] is True


def test_run_eval_returns_error_for_unknown_eval(
    monkeypatch,
    capsys,
) -> None:
    async def _fake_run_eval_scenario(
        scenario_name: str,
        *,
        output_root: Path,
    ) -> dict[str, object] | None:
        assert scenario_name == "missing-scenario"
        assert output_root == Path("sessions/evals")
        return None

    monkeypatch.setattr("runtime.cli.run_eval_scenario", _fake_run_eval_scenario)
    monkeypatch.setattr(
        "runtime.cli.list_eval_scenarios",
        lambda: (
            EvalScenario(
                scenario_id="incident-chain-replay-recent-deployment",
                description="Supported path replay.",
                fixture_path=Path("evals/fixtures/incident_chain_recent_deployment.json"),
            ),
        ),
    )

    exit_code = main(["run-eval", "missing-scenario"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert (
        "unknown eval: missing-scenario. valid names: "
        "incident-chain-replay-recent-deployment"
    ) in captured.err


def test_run_eval_returns_failure_exit_code_when_eval_fails(
    monkeypatch,
    capsys,
) -> None:
    async def _fake_run_eval_scenario(
        scenario_name: str,
        *,
        output_root: Path,
    ) -> dict[str, object] | None:
        assert scenario_name == "scenario-failure"
        assert output_root == Path("sessions/evals")
        return {
            "scenario_id": scenario_name,
            "description": "Failure path replay.",
            "success": False,
            "verifier_pass_rate": 0.5,
            "session_id": "scenario-failure-session",
            "incident_id": "incident-failure",
            "output_root": "sessions/evals/scenario-failure-run",
            "checkpoint_path": (
                "sessions/evals/scenario-failure-run/checkpoints/scenario-failure.json"
            ),
            "transcript_path": (
                "sessions/evals/scenario-failure-run/transcripts/scenario-failure.jsonl"
            ),
            "working_memory_path": (
                "sessions/evals/scenario-failure-run/working_memory/incident-failure.json"
            ),
            "current_phase": "recommendation_failed_artifacts",
            "final_stage": "recommendation",
            "path_classification": "failure_recovery",
            "handoff_status": "failed",
            "handoff_path": None,
            "handoff_available": False,
            "signals": ["recommendation: failure - missing artifact"],
            "notes": [],
            "stages": [],
        }

    monkeypatch.setattr("runtime.cli.run_eval_scenario", _fake_run_eval_scenario)

    exit_code = main(["run-eval", "scenario-failure", "--json"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["path_classification"] == "failure_recovery"
    assert payload["handoff_status"] == "failed"


def test_incident_chain_replay_lookup_accepts_underscore_alias() -> None:
    scenario = incident_chain_replay_scenario_by_id("incident_chain_recent_deployment")

    assert scenario is not None
    assert scenario.scenario_id == "incident-chain-replay-recent-deployment"
