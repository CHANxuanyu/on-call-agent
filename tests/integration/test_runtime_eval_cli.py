import json
from pathlib import Path

from runtime.cli import main


def test_list_evals_json_lists_available_replay_scenarios(capsys) -> None:
    exit_code = main(["list-evals", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [scenario["name"] for scenario in payload["scenarios"]] == [
        "incident-chain-replay-recent-deployment",
        "incident-chain-replay-insufficient-evidence",
    ]


def test_run_eval_json_runs_supported_path_scenario(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = main(
        [
            "run-eval",
            "incident-chain-replay-recent-deployment",
            "--output-root",
            str(tmp_path / "evals"),
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    output_root = Path(payload["output_root"])
    assert payload["scenario_id"] == "incident-chain-replay-recent-deployment"
    assert payload["success"] is True
    assert payload["path_classification"] == "supported"
    assert payload["final_stage"] == "action_stub"
    assert payload["handoff_status"] == "written"
    assert payload["handoff_available"] is True
    assert output_root.exists()
    assert output_root.parent == tmp_path / "evals"
    assert Path(payload["checkpoint_path"]).exists()
    assert Path(payload["transcript_path"]).exists()
    assert Path(payload["handoff_path"]).exists()


def test_run_eval_json_accepts_underscore_alias(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = main(
        [
            "run-eval",
            "incident_chain_recent_deployment",
            "--output-root",
            str(tmp_path / "evals"),
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scenario_id"] == "incident-chain-replay-recent-deployment"
    assert payload["success"] is True
    assert payload["path_classification"] == "supported"


def test_run_eval_json_runs_conservative_path_scenario(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = main(
        [
            "run-eval",
            "incident-chain-replay-insufficient-evidence",
            "--output-root",
            str(tmp_path / "evals"),
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scenario_id"] == "incident-chain-replay-insufficient-evidence"
    assert payload["success"] is True
    assert payload["path_classification"] == "conservative"
    assert payload["current_phase"] == "action_stub_not_actionable"
    assert payload["final_stage"] == "action_stub"
    assert payload["handoff_status"] == "written"
    assert payload["handoff_available"] is True
    assert "recommendation_type=investigate_more" in payload["notes"]
