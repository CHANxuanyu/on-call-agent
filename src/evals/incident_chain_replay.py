"""Small replay-style eval for the current incident artifact chain."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field

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
from evals.models import EvalResult, EvalScenario
from tools.implementations.follow_up_investigation import InvestigationTarget
from tools.implementations.incident_action_stub import ActionCandidateType
from tools.implementations.incident_hypothesis import HypothesisType
from tools.implementations.incident_recommendation import RecommendationType
from tools.implementations.incident_triage import IncidentSeverity
from verifiers.base import VerifierStatus
from verifiers.implementations.evidence_reading import EvidenceReadBranch
from verifiers.implementations.follow_up_investigation import FollowUpBranch
from verifiers.implementations.incident_action_stub import ActionStubBranch
from verifiers.implementations.incident_hypothesis import HypothesisBranch
from verifiers.implementations.incident_recommendation import RecommendationBranch

DEFAULT_INCIDENT_CHAIN_REPLAY_VERIFIERS = (
    "incident_triage_output",
    "incident_follow_up_outcome",
    "incident_evidence_read_outcome",
    "incident_hypothesis_outcome",
    "incident_recommendation_outcome",
    "incident_action_stub_outcome",
)


class IncidentChainReplayFixture(BaseModel):
    """Fixture content for the narrow incident chain replay."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    service: str = Field(min_length=1)
    symptoms: list[str] = Field(min_length=1)
    impact_summary: str = Field(min_length=1)
    severity_hint: IncidentSeverity | None = None
    recent_deployment: str | None = None
    runbook_reference: str | None = None
    ownership_team: str | None = None
    expected_follow_up_target: InvestigationTarget
    expected_evidence_snapshot: str = Field(min_length=1)
    expected_hypothesis_type: HypothesisType
    expected_hypothesis_supported: bool
    expected_recommendation_type: RecommendationType
    expected_recommendation_requires_approval: bool
    expected_action_candidate_type: ActionCandidateType
    expected_action_candidate_created: bool
    expected_action_stub_requires_approval: bool


@dataclass(frozen=True, slots=True)
class _IncidentChainReplayScenarioDefinition:
    scenario_id: str
    description: str
    fixture_filename: str


DEFAULT_INCIDENT_CHAIN_REPLAY_SCENARIO_DEFINITIONS = (
    _IncidentChainReplayScenarioDefinition(
        scenario_id="incident-chain-replay-recent-deployment",
        description=(
            "Replay triage, follow-up, evidence, hypothesis, recommendation, "
            "and action stub for a supported recent-deployment case."
        ),
        fixture_filename="incident_chain_recent_deployment.json",
    ),
    _IncidentChainReplayScenarioDefinition(
        scenario_id="incident-chain-replay-insufficient-evidence",
        description=(
            "Replay triage, follow-up, evidence, hypothesis, recommendation, "
            "and action stub for an insufficient-evidence conservative case."
        ),
        fixture_filename="incident_chain_insufficient_evidence.json",
    ),
)


@dataclass(frozen=True, slots=True)
class IncidentChainReplayExecution:
    """Structured replay execution details with preserved artifact roots."""

    scenario: EvalScenario
    result: EvalResult
    session_id: str
    incident_id: str | None
    artifacts_root: Path
    checkpoint_root: Path
    transcript_root: Path
    working_memory_root: Path


def default_incident_chain_replay_scenarios(
    *,
    fixtures_root: Path = Path("evals/fixtures"),
) -> tuple[EvalScenario, ...]:
    """Return the stable built-in replay scenarios in display order."""

    return tuple(
        EvalScenario(
            scenario_id=definition.scenario_id,
            description=definition.description,
            fixture_path=fixtures_root / definition.fixture_filename,
            expected_verifiers=list(DEFAULT_INCIDENT_CHAIN_REPLAY_VERIFIERS),
        )
        for definition in DEFAULT_INCIDENT_CHAIN_REPLAY_SCENARIO_DEFINITIONS
    )


def incident_chain_replay_scenario_by_id(
    scenario_id: str,
    *,
    fixtures_root: Path = Path("evals/fixtures"),
) -> EvalScenario | None:
    """Look up one built-in replay scenario by canonical id or fixture-stem alias."""

    for scenario in default_incident_chain_replay_scenarios(fixtures_root=fixtures_root):
        valid_names = {scenario.scenario_id}
        if scenario.fixture_path is not None:
            valid_names.add(scenario.fixture_path.stem)
        if scenario_id in valid_names:
            return scenario
    return None


@dataclass(slots=True)
class IncidentChainReplayRunner:
    """Replays the triage, follow-up, and evidence-reading chain from fixture input."""

    skills_root: Path = Path("skills")
    evidence_fixtures_path: Path = Path("evals/fixtures/evidence_snapshots.json")

    async def run(self, scenario: EvalScenario) -> EvalResult:
        with TemporaryDirectory() as temp_dir:
            execution = await self.run_with_artifacts(
                scenario,
                artifacts_root=Path(temp_dir),
            )
        return execution.result

    async def run_with_artifacts(
        self,
        scenario: EvalScenario,
        *,
        artifacts_root: Path,
    ) -> IncidentChainReplayExecution:
        """Run one replay scenario while preserving the resulting artifacts."""

        checkpoint_root = artifacts_root / "checkpoints"
        transcript_root = artifacts_root / "transcripts"
        working_memory_root = artifacts_root / "working_memory"
        session_id = f"{scenario.scenario_id}-session"

        if scenario.fixture_path is None:
            return IncidentChainReplayExecution(
                scenario=scenario,
                result=EvalResult(
                    scenario_id=scenario.scenario_id,
                    success=False,
                    verifier_pass_rate=0.0,
                    notes=["scenario fixture path is required"],
                ),
                session_id=session_id,
                incident_id=None,
                artifacts_root=artifacts_root,
                checkpoint_root=checkpoint_root,
                transcript_root=transcript_root,
                working_memory_root=working_memory_root,
            )

        fixture = IncidentChainReplayFixture.model_validate(
            json.loads(scenario.fixture_path.read_text(encoding="utf-8"))
        )
        artifacts_root.mkdir(parents=True, exist_ok=True)
        result = await self._run_loaded_fixture(
            scenario=scenario,
            fixture=fixture,
            session_id=session_id,
            artifacts_root=artifacts_root,
        )
        return IncidentChainReplayExecution(
            scenario=scenario,
            result=result,
            session_id=session_id,
            incident_id=fixture.incident_id,
            artifacts_root=artifacts_root,
            checkpoint_root=checkpoint_root,
            transcript_root=transcript_root,
            working_memory_root=working_memory_root,
        )

    async def _run_loaded_fixture(
        self,
        *,
        scenario: EvalScenario,
        fixture: IncidentChainReplayFixture,
        session_id: str,
        artifacts_root: Path,
    ) -> EvalResult:
        triage_step = IncidentTriageStep(
            skills_root=self.skills_root,
            transcript_root=artifacts_root / "transcripts",
            checkpoint_root=artifacts_root / "checkpoints",
        )
        follow_up_step = IncidentFollowUpStep(
            transcript_root=artifacts_root / "transcripts",
            checkpoint_root=artifacts_root / "checkpoints",
        )
        evidence_step = IncidentEvidenceStep(
            transcript_root=artifacts_root / "transcripts",
            checkpoint_root=artifacts_root / "checkpoints",
        )
        hypothesis_step = IncidentHypothesisStep(
            transcript_root=artifacts_root / "transcripts",
            checkpoint_root=artifacts_root / "checkpoints",
        )
        recommendation_step = IncidentRecommendationStep(
            transcript_root=artifacts_root / "transcripts",
            checkpoint_root=artifacts_root / "checkpoints",
        )
        action_stub_step = IncidentActionStubStep(
            transcript_root=artifacts_root / "transcripts",
            checkpoint_root=artifacts_root / "checkpoints",
        )
        evidence_step.tool.fixtures_path = self.evidence_fixtures_path

        triage_result = await triage_step.run(
            IncidentTriageStepRequest(
                session_id=session_id,
                incident_id=fixture.incident_id,
                title=fixture.title,
                service=fixture.service,
                symptoms=fixture.symptoms,
                impact_summary=fixture.impact_summary,
                severity_hint=fixture.severity_hint,
                recent_deployment=fixture.recent_deployment,
                runbook_reference=fixture.runbook_reference,
                ownership_team=fixture.ownership_team,
            )
        )
        follow_up_result = await follow_up_step.run(
            IncidentFollowUpStepRequest(session_id=session_id)
        )
        evidence_result = await evidence_step.run(
            IncidentEvidenceStepRequest(session_id=session_id)
        )
        hypothesis_result = await hypothesis_step.run(
            IncidentHypothesisStepRequest(session_id=session_id)
        )
        recommendation_result = await recommendation_step.run(
            IncidentRecommendationStepRequest(session_id=session_id)
        )
        action_stub_result = await action_stub_step.run(
            IncidentActionStubStepRequest(session_id=session_id)
        )

        follow_up_target = (
            follow_up_result.investigation_output.investigation_target
            if follow_up_result.investigation_output is not None
            else None
        )
        evidence_snapshot = (
            evidence_result.evidence_output.snapshot_id
            if evidence_result.evidence_output is not None
            else "missing"
        )
        hypothesis_type = (
            hypothesis_result.hypothesis_output.hypothesis_type
            if hypothesis_result.hypothesis_output is not None
            else None
        )
        hypothesis_supported = (
            hypothesis_result.hypothesis_output.evidence_supported
            if hypothesis_result.hypothesis_output is not None
            else None
        )
        recommendation_type = (
            recommendation_result.recommendation_output.recommendation_type
            if recommendation_result.recommendation_output is not None
            else None
        )
        recommendation_requires_approval = (
            recommendation_result.future_action_requires_approval
        )
        action_candidate_type = (
            action_stub_result.action_stub_output.action_candidate_type
            if action_stub_result.action_stub_output is not None
            else None
        )
        action_candidate_created = action_stub_result.action_candidate_produced
        action_stub_requires_approval = action_stub_result.approval_required
        passes = [
            triage_result.verifier_result.status is VerifierStatus.PASS,
            follow_up_result.verifier_result.status is VerifierStatus.PASS,
            evidence_result.verifier_result.status is VerifierStatus.PASS,
            hypothesis_result.verifier_result.status is VerifierStatus.PASS,
            recommendation_result.verifier_result.status is VerifierStatus.PASS,
            action_stub_result.verifier_result.status is VerifierStatus.PASS,
            follow_up_result.branch is FollowUpBranch.INVESTIGATE,
            evidence_result.branch is EvidenceReadBranch.READ_EVIDENCE,
            hypothesis_result.branch is HypothesisBranch.BUILD_HYPOTHESIS,
            recommendation_result.branch is RecommendationBranch.BUILD_RECOMMENDATION,
            action_stub_result.branch is ActionStubBranch.BUILD_ACTION_STUB,
            follow_up_target == fixture.expected_follow_up_target,
            evidence_result.evidence_output is not None
            and evidence_snapshot == fixture.expected_evidence_snapshot,
            hypothesis_type == fixture.expected_hypothesis_type,
            hypothesis_supported is fixture.expected_hypothesis_supported,
            recommendation_type == fixture.expected_recommendation_type,
            recommendation_requires_approval
            is fixture.expected_recommendation_requires_approval,
            action_candidate_type == fixture.expected_action_candidate_type,
            action_candidate_created is fixture.expected_action_candidate_created,
            action_stub_requires_approval is fixture.expected_action_stub_requires_approval,
        ]
        verifier_pass_rate = sum(passes) / len(passes)
        return EvalResult(
            scenario_id=scenario.scenario_id,
            success=all(passes),
            verifier_pass_rate=verifier_pass_rate,
            notes=[
                f"follow_up_target={follow_up_target}",
                f"evidence_branch={evidence_result.branch}",
                f"evidence_snapshot={evidence_snapshot}",
                f"hypothesis_branch={hypothesis_result.branch}",
                f"hypothesis_type={hypothesis_type}",
                f"recommendation_branch={recommendation_result.branch}",
                f"recommendation_type={recommendation_type}",
                f"action_stub_branch={action_stub_result.branch}",
                f"action_candidate_type={action_candidate_type}",
            ],
        )
