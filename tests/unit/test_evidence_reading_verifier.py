import pytest

from tools.implementations.evidence_reading import EvidenceReadOutput
from tools.implementations.follow_up_investigation import InvestigationTarget
from verifiers.base import VerifierRequest, VerifierStatus
from verifiers.implementations.evidence_reading import (
    EvidenceReadBranch,
    EvidenceReadOutcomeVerifier,
)


def _evidence_output(target: InvestigationTarget) -> EvidenceReadOutput:
    return EvidenceReadOutput(
        incident_id="incident-500",
        service="payments-api",
        investigation_target=target,
        snapshot_id="deployment-record-2026-04-01",
        evidence_source="evals/fixtures/evidence_snapshots.json::recent_deployment",
        evidence_summary="A recent deployment changed request timeout handling.",
        observations=["deploy completed 12 minutes before alert"],
        recommended_next_read_only_action="Review the deployment diff for payments-api.",
    )


@pytest.mark.asyncio
async def test_evidence_read_outcome_verifier_passes_valid_evidence_branch() -> None:
    verifier = EvidenceReadOutcomeVerifier()
    evidence_output = _evidence_output(InvestigationTarget.RECENT_DEPLOYMENT)

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-500",
            inputs={
                "branch": EvidenceReadBranch.READ_EVIDENCE,
                "follow_up_phase": "follow_up_investigation_selected",
                "follow_up_verifier_passed": True,
                "selected_target": InvestigationTarget.RECENT_DEPLOYMENT,
                "evidence_output": evidence_output.model_dump(mode="json"),
            },
        )
    )

    assert result.status is VerifierStatus.PASS


@pytest.mark.asyncio
async def test_evidence_read_outcome_verifier_passes_justified_insufficient_state() -> None:
    verifier = EvidenceReadOutcomeVerifier()

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-500",
            inputs={
                "branch": EvidenceReadBranch.INSUFFICIENT_STATE,
                "follow_up_phase": "follow_up_complete_no_action",
                "follow_up_verifier_passed": False,
                "selected_target": None,
                "insufficiency_reason": (
                    "Prior artifacts do not yet contain a verified selected "
                    "investigation target."
                ),
                "evidence_output": None,
            },
        )
    )

    assert result.status is VerifierStatus.PASS


@pytest.mark.asyncio
async def test_evidence_read_outcome_verifier_rejects_globally_valid_wrong_family_phase(
) -> None:
    verifier = EvidenceReadOutcomeVerifier()

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-500",
            inputs={
                "branch": EvidenceReadBranch.INSUFFICIENT_STATE,
                "follow_up_phase": "triage_completed",
                "follow_up_verifier_passed": False,
                "selected_target": None,
                "insufficiency_reason": "No follow-up target exists yet.",
                "evidence_output": None,
            },
        )
    )

    assert result.status is VerifierStatus.UNVERIFIED
    assert result.diagnostics[0].code == "invalid_evidence_read_inputs"


@pytest.mark.asyncio
async def test_evidence_read_outcome_verifier_rejects_missing_selected_target_in_selected_phase(
) -> None:
    verifier = EvidenceReadOutcomeVerifier()

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-500",
            inputs={
                "branch": EvidenceReadBranch.INSUFFICIENT_STATE,
                "follow_up_phase": "follow_up_investigation_selected",
                "follow_up_verifier_passed": True,
                "selected_target": None,
                "insufficiency_reason": "Transcript is missing the selected target.",
                "evidence_output": None,
            },
        )
    )

    assert result.status is VerifierStatus.FAIL
    assert result.diagnostics[0].code == "missing_selected_target"
