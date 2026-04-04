"""Helpers that normalize tool and verifier execution into stable artifacts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from runtime.models import (
    SyntheticFailure,
    SyntheticFailureCode,
    SyntheticFailureSource,
)
from tools.models import ToolFailure, ToolResult, ToolResultStatus
from verifiers.base import (
    VerifierDiagnostic,
    VerifierResult,
    VerifierRetryHint,
    VerifierStatus,
)

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


def _model_payload(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    return value


def build_synthetic_tool_result(
    *,
    step_name: str,
    tool_name: str,
    code: SyntheticFailureCode,
    reason: str,
    details: dict[str, object] | None = None,
) -> ToolResult:
    synthetic_failure = SyntheticFailure(
        code=code,
        source=SyntheticFailureSource.TOOL,
        step_name=step_name,
        tool_name=tool_name,
        reason=reason,
        details=details or {},
    )
    return ToolResult(
        status=ToolResultStatus.FAILED,
        failure=ToolFailure(
            code=code.value,
            message=reason,
            synthetic_failure=synthetic_failure,
        ),
    )


def build_synthetic_verifier_result(
    *,
    step_name: str,
    verifier_name: str,
    code: SyntheticFailureCode,
    reason: str,
    details: dict[str, object] | None = None,
) -> VerifierResult:
    synthetic_failure = SyntheticFailure(
        code=code,
        source=SyntheticFailureSource.VERIFIER,
        step_name=step_name,
        verifier_name=verifier_name,
        reason=reason,
        details=details or {},
    )
    return VerifierResult(
        status=VerifierStatus.UNVERIFIED,
        summary=reason,
        diagnostics=[
            VerifierDiagnostic(
                code=code.value,
                message=reason,
            )
        ],
        retry_hint=VerifierRetryHint(
            should_retry=False,
            reason="Resolve the synthetic verifier failure before retrying.",
        ),
        synthetic_failure=synthetic_failure,
    )


async def execute_tool_with_invariants(
    *,
    step_name: str,
    tool_name: str,
    execute: Callable[[], Awaitable[object]],
) -> ToolResult:
    try:
        raw_result = await execute()
    except Exception as exc:
        return build_synthetic_tool_result(
            step_name=step_name,
            tool_name=tool_name,
            code=SyntheticFailureCode.TOOL_EXECUTION_FAILED,
            reason=f"Tool execution raised an exception in step '{step_name}'.",
            details={
                "exception_type": exc.__class__.__name__,
                "exception_message": str(exc),
            },
        )

    try:
        return ToolResult.model_validate(_model_payload(raw_result))
    except ValidationError as exc:
        return build_synthetic_tool_result(
            step_name=step_name,
            tool_name=tool_name,
            code=SyntheticFailureCode.TOOL_RESULT_INVALID,
            reason=(
                f"Tool '{tool_name}' in step '{step_name}' returned an invalid ToolResult."
            ),
            details={"validation_error": str(exc)},
        )


def normalize_tool_output(
    *,
    step_name: str,
    tool_name: str,
    tool_result: ToolResult,
    output_model: type[OutputModelT],
) -> tuple[ToolResult, OutputModelT | None]:
    if tool_result.failure is not None:
        return tool_result, None

    if not tool_result.output:
        return (
            build_synthetic_tool_result(
                step_name=step_name,
                tool_name=tool_name,
                code=SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED,
                reason=(
                    f"Tool '{tool_name}' in step '{step_name}' completed without "
                    "producing structured output."
                ),
            ),
            None,
        )

    try:
        output = output_model.model_validate(tool_result.output)
    except ValidationError as exc:
        return (
            build_synthetic_tool_result(
                step_name=step_name,
                tool_name=tool_name,
                code=SyntheticFailureCode.TOOL_OUTPUT_VALIDATION_FAILED,
                reason=(
                    f"Tool '{tool_name}' in step '{step_name}' returned output that failed "
                    "typed validation."
                ),
                details={"validation_error": str(exc)},
            ),
            None,
        )

    return tool_result, output


async def execute_verifier_with_invariants(
    *,
    step_name: str,
    verifier_name: str,
    execute: Callable[[], Awaitable[object]],
) -> VerifierResult:
    try:
        raw_result = await execute()
    except Exception as exc:
        return build_synthetic_verifier_result(
            step_name=step_name,
            verifier_name=verifier_name,
            code=SyntheticFailureCode.VERIFIER_EXECUTION_FAILED,
            reason=f"Verifier execution raised an exception in step '{step_name}'.",
            details={
                "exception_type": exc.__class__.__name__,
                "exception_message": str(exc),
            },
        )

    try:
        return VerifierResult.model_validate(_model_payload(raw_result))
    except ValidationError as exc:
        return build_synthetic_verifier_result(
            step_name=step_name,
            verifier_name=verifier_name,
            code=SyntheticFailureCode.VERIFIER_RESULT_INVALID,
            reason=(
                f"Verifier '{verifier_name}' in step '{step_name}' returned an invalid "
                "VerifierResult."
            ),
            details={"validation_error": str(exc)},
        )
