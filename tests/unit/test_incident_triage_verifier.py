import pytest

from tools.implementations.incident_triage import IncidentSeverity, IncidentTriageOutput
from verifiers.base import VerifierKind, VerifierRequest, VerifierStatus
from verifiers.implementations.incident_triage import IncidentTriageOutputVerifier


@pytest.mark.asyncio
async def test_incident_triage_output_verifier_passes_on_actionable_output() -> None:
    verifier = IncidentTriageOutputVerifier()
    triage_output = IncidentTriageOutput(
        incident_id="incident-100",
        service="payments-api",
        incident_summary="Elevated 5xx errors affecting payments-api.",
        suspected_severity=IncidentSeverity.HIGH,
        suspected_blast_radius="Customer-facing impact is likely centered on payments-api.",
        recommended_next_action="Inspect the latest incident evidence for payments-api.",
        unknowns=[],
    )

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-100",
            inputs={"triage_output": triage_output.model_dump(mode="json")},
        )
    )

    assert result.status is VerifierStatus.PASS
    assert result.diagnostics == []


@pytest.mark.asyncio
async def test_incident_triage_output_verifier_fails_on_non_actionable_next_step() -> None:
    verifier = IncidentTriageOutputVerifier()
    triage_output = IncidentTriageOutput(
        incident_id="incident-101",
        service="payments-api",
        incident_summary="Elevated 5xx errors affecting payments-api.",
        suspected_severity=IncidentSeverity.HIGH,
        suspected_blast_radius="Customer-facing impact is likely centered on payments-api.",
        recommended_next_action="Escalate later if needed.",
        unknowns=[],
    )

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-101",
            inputs={"triage_output": triage_output.model_dump(mode="json")},
        )
    )

    assert result.status is VerifierStatus.FAIL
    assert result.diagnostics[0].code == "non_actionable_next_step"


@pytest.mark.asyncio
async def test_incident_triage_output_verifier_reports_missing_contract_input() -> None:
    verifier = IncidentTriageOutputVerifier()

    result = await verifier.verify(
        VerifierRequest(
            name=verifier.definition.name,
            target="incident-102",
            inputs={},
        )
    )

    assert verifier.definition.kind is VerifierKind.OUTCOME
    assert result.status is VerifierStatus.UNVERIFIED
    assert result.diagnostics[0].code == "missing_triage_output"
