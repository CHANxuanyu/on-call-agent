from pathlib import Path

import pytest
from pydantic import BaseModel

from memory.checkpoints import JsonCheckpointStore, SessionCheckpoint
from permissions.models import (
    PermissionActionCategory,
    PermissionPolicySource,
    PermissionSafetyBoundary,
)
from permissions.policy import PermissionPolicy
from runtime.harness import (
    ResumableSliceHarness,
    combine_artifact_failure,
    pending_verifier_for_status,
)
from runtime.models import SyntheticFailureCode
from tools.models import (
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultStatus,
    ToolRiskLevel,
)
from transcripts.models import (
    CheckpointWrittenEvent,
    ModelStepEvent,
    PermissionDecisionEvent,
    ResumeStartedEvent,
    ToolRequestEvent,
    ToolResultEvent,
    VerifierResultEvent,
)
from transcripts.writer import JsonlTranscriptStore
from verifiers.base import (
    VerifierDefinition,
    VerifierRequest,
    VerifierResult,
    VerifierStatus,
)


class _HarnessOutput(BaseModel):
    value: str


class _ReadOnlySuccessTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="harness_test_tool",
            description="Read one deterministic harness test payload.",
            risk_level=ToolRiskLevel.READ_ONLY,
        )

    async def execute(self, call: ToolCall) -> ToolResult:
        del call
        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output={"value": "ok"},
        )


class _MalformedOutputTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="harness_test_tool",
            description="Return malformed output for harness testing.",
            risk_level=ToolRiskLevel.READ_ONLY,
        )

    async def execute(self, call: ToolCall) -> ToolResult:
        del call
        return ToolResult(
            status=ToolResultStatus.SUCCEEDED,
            output={"unexpected": "shape"},
        )


class _PassingVerifier:
    @property
    def definition(self) -> VerifierDefinition:
        return VerifierDefinition(
            name="harness_test_verifier",
            description="Pass when the harness produced a structured output.",
            target_condition="structured output exists",
        )

    async def verify(self, request: VerifierRequest) -> VerifierResult:
        del request
        return VerifierResult(
            status=VerifierStatus.PASS,
            summary="Structured output is present.",
        )


def _write_checkpoint(root: Path, *, session_id: str) -> Path:
    checkpoint_path = root / f"{session_id}.json"
    JsonCheckpointStore(checkpoint_path).write(
        SessionCheckpoint(
            checkpoint_id=f"{session_id}-checkpoint",
            session_id=session_id,
            incident_id=f"{session_id}-incident",
            current_phase="hypothesis_supported",
            current_step=4,
            summary_of_progress="Harness test checkpoint.",
        )
    )
    return checkpoint_path


@pytest.mark.asyncio
async def test_resumable_slice_harness_records_resume_tool_verifier_and_checkpoint(
    tmp_path: Path,
) -> None:
    checkpoint_root = tmp_path / "checkpoints"
    transcript_root = tmp_path / "transcripts"
    _write_checkpoint(checkpoint_root, session_id="harness-success")

    harness = ResumableSliceHarness.load(
        session_id="harness-success",
        step_name="test_harness_slice",
        checkpoint_root=checkpoint_root,
        transcript_root=transcript_root,
    )

    harness.emit_resume_started(reason="Resume harness test.")
    harness.emit_model_step(
        summary="The harness will run one deterministic tool and one verifier.",
        planned_verifiers=["harness_test_verifier"],
    )

    tool_outcome = await harness.execute_read_only_tool(
        tool=_ReadOnlySuccessTool(),
        permission_policy=PermissionPolicy(),
        tool_call=ToolCall(name="harness_test_tool", arguments={}),
        call_id="call-1",
        output_model=_HarnessOutput,
        permission_denied_message="harness test tool should always be allowed",
    )
    output = tool_outcome.output
    assert output is not None
    verifier_request = VerifierRequest(
        name="harness_test_verifier",
        target="harness-success-incident",
        inputs={"value": output.model_dump(mode="json")},
    )
    verifier_result = await harness.execute_verifier(
        verifier=_PassingVerifier(),
        request=verifier_request,
    )
    checkpoint = SessionCheckpoint(
        checkpoint_id="harness-success-next",
        session_id="harness-success",
        incident_id="harness-success-incident",
        current_phase="recommendation_supported",
        current_step=harness.step_index,
        pending_verifier=pending_verifier_for_status(
            verifier_name="harness_test_verifier",
            verifier_request=verifier_request,
            verifier_status=verifier_result.status,
        ),
        summary_of_progress="Harness test advanced to the next phase.",
    )
    harness.write_checkpoint(checkpoint)

    events = JsonlTranscriptStore(transcript_root / "harness-success.jsonl").read_all()
    stored_checkpoint = JsonCheckpointStore(checkpoint_root / "harness-success.json").load()

    assert output.value == "ok"
    assert verifier_result.status is VerifierStatus.PASS
    assert isinstance(events[0], ResumeStartedEvent)
    assert isinstance(events[1], ModelStepEvent)
    assert isinstance(events[2], PermissionDecisionEvent)
    assert isinstance(events[3], ToolRequestEvent)
    assert isinstance(events[4], ToolResultEvent)
    assert isinstance(events[5], VerifierResultEvent)
    assert isinstance(events[6], CheckpointWrittenEvent)
    permission_event = events[2]
    assert isinstance(permission_event, PermissionDecisionEvent)
    assert (
        permission_event.decision.provenance.policy_source
        is PermissionPolicySource.DEFAULT_SAFE_TOOL_RISK
    )
    assert (
        permission_event.decision.provenance.action_category
        is PermissionActionCategory.TOOL_EXECUTION
    )
    assert (
        permission_event.decision.provenance.safety_boundary
        is PermissionSafetyBoundary.READ_ONLY_ONLY
    )
    assert any(
        "shared resumable-slice harness" in note
        for note in permission_event.decision.provenance.notes
    )
    assert stored_checkpoint.current_phase == "recommendation_supported"
    assert stored_checkpoint.pending_verifier is None


@pytest.mark.asyncio
async def test_resumable_slice_harness_normalizes_malformed_tool_output(
    tmp_path: Path,
) -> None:
    checkpoint_root = tmp_path / "checkpoints"
    transcript_root = tmp_path / "transcripts"
    _write_checkpoint(checkpoint_root, session_id="harness-malformed")

    harness = ResumableSliceHarness.load(
        session_id="harness-malformed",
        step_name="test_harness_slice",
        checkpoint_root=checkpoint_root,
        transcript_root=transcript_root,
    )

    harness.emit_resume_started(reason="Resume malformed-output harness test.")
    harness.emit_model_step(
        summary="The harness will normalize malformed tool output.",
        planned_verifiers=["harness_test_verifier"],
    )
    tool_outcome = await harness.execute_read_only_tool(
        tool=_MalformedOutputTool(),
        permission_policy=PermissionPolicy(),
        tool_call=ToolCall(name="harness_test_tool", arguments={}),
        call_id="call-1",
        output_model=_HarnessOutput,
        permission_denied_message="harness test tool should always be allowed",
    )
    verifier_result = VerifierResult(
        status=VerifierStatus.UNVERIFIED,
        summary="No structured output was available to verify.",
    )
    artifact_failure = combine_artifact_failure(
        prior_failure=None,
        tool_result=tool_outcome.tool_result,
        verifier_result=verifier_result,
    )

    events = JsonlTranscriptStore(transcript_root / "harness-malformed.jsonl").read_all()

    assert tool_outcome.output is None
    assert tool_outcome.tool_result.failure is not None
    assert tool_outcome.tool_result.failure.synthetic_failure is not None
    assert (
        tool_outcome.tool_result.failure.synthetic_failure.code
        is SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED
    )
    assert artifact_failure is not None
    assert artifact_failure.code is SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED
    assert isinstance(events[0], ResumeStartedEvent)
    assert isinstance(events[1], ModelStepEvent)
    assert isinstance(events[2], PermissionDecisionEvent)
    assert isinstance(events[3], ToolRequestEvent)
    assert isinstance(events[4], ToolResultEvent)
