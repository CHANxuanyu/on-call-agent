from __future__ import annotations

import pytest
from pydantic import BaseModel

from runtime.execution import (
    execute_tool_with_invariants,
    execute_verifier_with_invariants,
    normalize_tool_output,
)
from runtime.models import SyntheticFailureCode
from tools.implementations.incident_recommendation import IncidentRecommendationOutput
from tools.models import ToolResult, ToolResultStatus
from verifiers.base import VerifierStatus


class _DummyOutput(BaseModel):
    value: str


@pytest.mark.asyncio
async def test_execute_tool_with_invariants_normalizes_invalid_tool_result() -> None:
    async def _invalid_tool_execution() -> object:
        return {"unexpected": "shape"}

    result = await execute_tool_with_invariants(
        step_name="test_step",
        tool_name="bad_tool",
        execute=_invalid_tool_execution,
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.synthetic_failure is not None
    assert result.failure.synthetic_failure.code is SyntheticFailureCode.TOOL_RESULT_INVALID


def test_normalize_tool_output_converts_malformed_output_to_synthetic_failure() -> None:
    tool_result = ToolResult(
        status=ToolResultStatus.SUCCEEDED,
        output={"unexpected": "shape"},
    )

    normalized_result, output = normalize_tool_output(
        step_name="test_step",
        tool_name="bad_tool",
        tool_result=tool_result,
        output_model=IncidentRecommendationOutput,
    )

    assert output is None
    assert normalized_result.status is ToolResultStatus.FAILED
    assert normalized_result.failure is not None
    assert normalized_result.failure.synthetic_failure is not None
    assert (
        normalized_result.failure.synthetic_failure.code
        is SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED
    )


@pytest.mark.asyncio
async def test_execute_verifier_with_invariants_normalizes_invalid_verifier_result() -> None:
    async def _invalid_verifier_execution() -> object:
        return {"unexpected": "shape"}

    result = await execute_verifier_with_invariants(
        step_name="test_step",
        verifier_name="bad_verifier",
        execute=_invalid_verifier_execution,
    )

    assert result.status is VerifierStatus.UNVERIFIED
    assert result.synthetic_failure is not None
    assert result.synthetic_failure.code is SyntheticFailureCode.VERIFIER_RESULT_INVALID
