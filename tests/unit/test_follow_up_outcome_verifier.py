import pytest

from tools.implementations.follow_up_investigation import (
    FollowUpInvestigationOutput,
    InvestigationTarget,
)
from tools.implementations.incident_triage import IncidentSeverity, IncidentTriageOutput
from verifiers.base import VerifierRequest, VerifierStatus
from verifiers.implementations.follow_up_investigation import (
    FollowUpBranch,
    FollowUpOutcomeVerifier,
)


def _triage_output(*, unknowns: list[str]) -> IncidentTriageOutput:
    return IncidentTriageOutput(
        incident_id="incident-300",
        service="payments-api",
        incident_summary="Checkout traffic is degraded.",
        suspected_severity=IncidentSeverity.HIGH,
        suspected_blast_radius="Customer-facing impact is likely centered on payments-api.",
        recommended_next_action="Inspect the latest incident evidence for payments-api.",
        unknowns=unknowns,
    )


@pytest.mark.asyncio
async def test_follow_up_outcome_verifier_passes_safe_no_op_branch() -> None:
    verifier = FollowUpOutcomeVerifier()

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-300",
            inputs={
                "branch": FollowUpBranch.NO_OP,
                "triage_verifier_passed": True,
                "triage_output": _triage_output(unknowns=[]).model_dump(mode="json"),
                "investigation_output": None,
            },
        )
    )

    assert result.status is VerifierStatus.PASS


@pytest.mark.asyncio
async def test_follow_up_outcome_verifier_passes_investigation_branch() -> None:
    verifier = FollowUpOutcomeVerifier()
    investigation_output = FollowUpInvestigationOutput(
        incident_id="incident-300",
        service="payments-api",
        investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
        evidence_gap="Recent deployment context is unavailable.",
        rationale="Deployment context is the first missing input.",
        recommended_read_only_action="Inspect the latest deployment record for payments-api.",
    )

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-300",
            inputs={
                "branch": FollowUpBranch.INVESTIGATE,
                "triage_verifier_passed": True,
                "triage_output": _triage_output(
                    unknowns=["Recent deployment context is unavailable."]
                ).model_dump(mode="json"),
                "investigation_output": investigation_output.model_dump(mode="json"),
            },
        )
    )

    assert result.status is VerifierStatus.PASS


@pytest.mark.asyncio
async def test_follow_up_outcome_verifier_rejects_invalid_no_op_branch() -> None:
    verifier = FollowUpOutcomeVerifier()

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-300",
            inputs={
                "branch": FollowUpBranch.NO_OP,
                "triage_verifier_passed": True,
                "triage_output": _triage_output(
                    unknowns=["Recent deployment context is unavailable."]
                ).model_dump(mode="json"),
                "investigation_output": None,
            },
        )
    )

    assert result.status is VerifierStatus.FAIL
    assert result.diagnostics[0].code == "follow_up_required"
