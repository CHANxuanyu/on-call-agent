from pathlib import Path

import pytest

from evals.incident_chain_replay import IncidentChainReplayRunner
from evals.models import EvalScenario


@pytest.mark.asyncio
async def test_incident_chain_replay_eval_runs_supported_hypothesis_chain() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    runner = IncidentChainReplayRunner(
        skills_root=repo_root / "skills",
        evidence_fixtures_path=repo_root / "evals/fixtures/evidence_snapshots.json",
    )
    scenario = EvalScenario(
        scenario_id="incident-chain-replay-recent-deployment",
        description="Replay triage, follow-up, and evidence read for a recent deployment case.",
        fixture_path=repo_root / "evals/fixtures/incident_chain_recent_deployment.json",
        expected_verifiers=[
            "incident_triage_output",
            "incident_follow_up_outcome",
            "incident_evidence_read_outcome",
            "incident_hypothesis_outcome",
            "incident_recommendation_outcome",
            "incident_action_stub_outcome",
        ],
    )

    result = await runner.run(scenario)

    assert result.success is True
    assert result.verifier_pass_rate == 1.0
    assert "follow_up_target=recent_deployment" in result.notes
    assert "hypothesis_type=deployment_regression" in result.notes
    assert "recommendation_type=validate_recent_deployment" in result.notes
    assert "action_candidate_type=rollback_recent_deployment_candidate" in result.notes


@pytest.mark.asyncio
async def test_incident_chain_replay_eval_runs_insufficient_evidence_chain() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    runner = IncidentChainReplayRunner(
        skills_root=repo_root / "skills",
        evidence_fixtures_path=repo_root / "evals/fixtures/evidence_snapshots.json",
    )
    scenario = EvalScenario(
        scenario_id="incident-chain-replay-insufficient-evidence",
        description=(
            "Replay triage, follow-up, evidence read, and hypothesis for a "
            "runbook-driven insufficient-evidence case."
        ),
        fixture_path=repo_root / "evals/fixtures/incident_chain_insufficient_evidence.json",
        expected_verifiers=[
            "incident_triage_output",
            "incident_follow_up_outcome",
            "incident_evidence_read_outcome",
            "incident_hypothesis_outcome",
            "incident_recommendation_outcome",
            "incident_action_stub_outcome",
        ],
    )

    result = await runner.run(scenario)

    assert result.success is True
    assert result.verifier_pass_rate == 1.0
    assert "follow_up_target=runbook" in result.notes
    assert "hypothesis_type=insufficient_evidence" in result.notes
    assert "recommendation_type=investigate_more" in result.notes
    assert "action_candidate_type=no_actionable_stub_yet" in result.notes
