from pathlib import Path

import pytest

from agent.incident_triage import IncidentTriageStep, IncidentTriageStepRequest
from agent.state import AgentStatus
from memory.checkpoints import JsonCheckpointStore
from runtime.models import SyntheticFailureCode
from tools.implementations.incident_triage import IncidentPayloadSummaryTool
from tools.models import ToolCall, ToolResult, ToolResultStatus
from transcripts.models import (
    CheckpointWrittenEvent,
    ToolResultEvent,
    VerifierRequestEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import (
    VerifierDefinition,
    VerifierKind,
    VerifierRequest,
    VerifierResult,
    VerifierStatus,
)
from verifiers.implementations.incident_triage import IncidentTriageOutputVerifier


def _request() -> IncidentTriageStepRequest:
    return IncidentTriageStepRequest(
        session_id="session-failure",
        incident_id="incident-failure",
        title="Elevated 5xx errors on payments-api",
        service="payments-api",
        symptoms=["spike in 5xx", "checkout requests timing out"],
        impact_summary="Customer checkout requests are failing intermittently.",
    )


def _step(
    tmp_path: Path,
    *,
    tool: object,
    verifier: object,
) -> IncidentTriageStep:
    repository_root = Path(__file__).resolve().parents[2]
    return IncidentTriageStep(
        skills_root=repository_root / "skills",
        transcript_root=tmp_path / "transcripts",
        checkpoint_root=tmp_path / "checkpoints",
        tool=tool,
        verifier=verifier,
    )


class _ToolRaises(IncidentPayloadSummaryTool):
    async def execute(self, call: ToolCall) -> ToolResult:
        del call
        raise RuntimeError("boom")


class _ToolReturnsInvalidResult(IncidentPayloadSummaryTool):
    async def execute(self, call: ToolCall) -> object:
        del call
        return {"unexpected": "shape"}


class _ToolReturnsMalformedOutput(IncidentPayloadSummaryTool):
    async def execute(self, call: ToolCall) -> ToolResult:
        del call
        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output={"unexpected": "shape"},
        )


class _VerifierRaises:
    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            kind=VerifierKind.OUTCOME,
            name="incident_triage_output",
            description="Raise during verification.",
            target_condition="never returns",
        )

    async def verify(self, request: VerifierRequest) -> VerifierResult:
        del request
        raise RuntimeError("boom")


class _VerifierReturnsInvalidResult:
    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            kind=VerifierKind.OUTCOME,
            name="incident_triage_output",
            description="Return malformed verifier output.",
            target_condition="never returns a valid result",
        )

    async def verify(self, request: VerifierRequest) -> object:
        del request
        return {"unexpected": "shape"}


def _events_and_checkpoint(result_path: Path, checkpoint_path: Path) -> tuple[list[object], object]:
    events = JsonlTranscriptStore(result_path).read_all()
    checkpoint = JsonCheckpointStore(checkpoint_path).load()
    return events, checkpoint


@pytest.mark.asyncio
async def test_incident_triage_step_fail_closes_when_tool_execution_raises(
    tmp_path: Path,
) -> None:
    result = await _step(
        tmp_path,
        tool=_ToolRaises(),
        verifier=IncidentTriageOutputVerifier(),
    ).run(_request())
    events, checkpoint = _events_and_checkpoint(result.transcript_path, result.checkpoint_path)

    assert result.completed is False
    assert result.status is AgentStatus.VERIFYING
    assert result.tool_result.failure is not None
    assert result.tool_result.failure.synthetic_failure is not None
    assert result.tool_result.failure.synthetic_failure.code is SyntheticFailureCode.TOOL_EXECUTION_FAILED
    assert result.verifier_result.status is VerifierStatus.UNVERIFIED
    assert checkpoint.current_phase == "triage_unverified"
    assert checkpoint.pending_verifier is not None
    assert isinstance(events[3], ToolResultEvent)
    assert isinstance(events[4], VerifierRequestEvent)
    assert isinstance(events[5], VerifierResultEvent)
    assert isinstance(events[6], CheckpointWrittenEvent)


@pytest.mark.asyncio
async def test_incident_triage_step_fail_closes_when_tool_result_is_invalid(
    tmp_path: Path,
) -> None:
    result = await _step(
        tmp_path,
        tool=_ToolReturnsInvalidResult(),
        verifier=IncidentTriageOutputVerifier(),
    ).run(_request())
    events, checkpoint = _events_and_checkpoint(result.transcript_path, result.checkpoint_path)

    assert result.completed is False
    assert result.status is AgentStatus.VERIFYING
    assert result.tool_result.failure is not None
    assert result.tool_result.failure.synthetic_failure is not None
    assert result.tool_result.failure.synthetic_failure.code is SyntheticFailureCode.TOOL_RESULT_INVALID
    assert result.verifier_result.status is VerifierStatus.UNVERIFIED
    assert checkpoint.current_phase == "triage_unverified"
    assert checkpoint.pending_verifier is not None
    assert isinstance(events[4], VerifierRequestEvent)
    assert isinstance(events[5], VerifierResultEvent)
    assert isinstance(events[6], CheckpointWrittenEvent)


@pytest.mark.asyncio
async def test_incident_triage_step_fail_closes_when_tool_output_is_malformed(
    tmp_path: Path,
) -> None:
    result = await _step(
        tmp_path,
        tool=_ToolReturnsMalformedOutput(),
        verifier=IncidentTriageOutputVerifier(),
    ).run(_request())
    events, checkpoint = _events_and_checkpoint(result.transcript_path, result.checkpoint_path)

    assert result.completed is False
    assert result.triage_output is None
    assert result.status is AgentStatus.VERIFYING
    assert result.tool_result.failure is not None
    assert result.tool_result.failure.synthetic_failure is not None
    assert (
        result.tool_result.failure.synthetic_failure.code
        is SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED
    )
    assert result.verifier_result.status is VerifierStatus.UNVERIFIED
    assert result.verifier_result.diagnostics[0].code == "invalid_triage_output"
    assert checkpoint.current_phase == "triage_unverified"
    assert checkpoint.pending_verifier is not None
    assert isinstance(events[4], VerifierRequestEvent)
    assert isinstance(events[5], VerifierResultEvent)


@pytest.mark.asyncio
async def test_incident_triage_step_fail_closes_when_verifier_raises(
    tmp_path: Path,
) -> None:
    result = await _step(
        tmp_path,
        tool=IncidentPayloadSummaryTool(),
        verifier=_VerifierRaises(),
    ).run(_request())
    events, checkpoint = _events_and_checkpoint(result.transcript_path, result.checkpoint_path)

    assert result.completed is False
    assert result.triage_output is not None
    assert result.status is AgentStatus.VERIFYING
    assert result.verifier_result.status is VerifierStatus.UNVERIFIED
    assert result.verifier_result.synthetic_failure is not None
    assert result.verifier_result.synthetic_failure.code is SyntheticFailureCode.VERIFIER_EXECUTION_FAILED
    assert checkpoint.current_phase == "triage_unverified"
    assert checkpoint.pending_verifier is not None
    assert isinstance(events[4], VerifierRequestEvent)
    assert isinstance(events[5], VerifierResultEvent)
    assert isinstance(events[6], CheckpointWrittenEvent)


@pytest.mark.asyncio
async def test_incident_triage_step_fail_closes_when_verifier_result_is_invalid(
    tmp_path: Path,
) -> None:
    result = await _step(
        tmp_path,
        tool=IncidentPayloadSummaryTool(),
        verifier=_VerifierReturnsInvalidResult(),
    ).run(_request())
    events, checkpoint = _events_and_checkpoint(result.transcript_path, result.checkpoint_path)

    assert result.completed is False
    assert result.triage_output is not None
    assert result.status is AgentStatus.VERIFYING
    assert result.verifier_result.status is VerifierStatus.UNVERIFIED
    assert result.verifier_result.synthetic_failure is not None
    assert result.verifier_result.synthetic_failure.code is SyntheticFailureCode.VERIFIER_RESULT_INVALID
    assert checkpoint.current_phase == "triage_unverified"
    assert checkpoint.pending_verifier is not None
    assert isinstance(events[4], VerifierRequestEvent)
    assert isinstance(events[5], VerifierResultEvent)
