"""Base models and protocol for first-class verifiers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from runtime.models import SyntheticFailure


class VerifierStatus(StrEnum):
    """Normalized verifier statuses."""

    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"


class VerifierKind(StrEnum):
    """Architectural category for a verifier implementation."""

    CONTRACT = "contract"
    OUTCOME = "outcome"


class VerifierDefinition(BaseModel):
    """Static metadata for a verifier."""

    model_config = ConfigDict(extra="forbid")

    kind: VerifierKind
    name: str
    description: str
    target_condition: str


class VerifierRequest(BaseModel):
    """Validated verifier invocation payload."""

    model_config = ConfigDict(extra="forbid")

    name: str
    target: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class VerifierDiagnostic(BaseModel):
    """Structured diagnostic emitted during verification."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class VerifierRetryHint(BaseModel):
    """Optional guidance for retrying a verification attempt."""

    model_config = ConfigDict(extra="forbid")

    should_retry: bool
    reason: str | None = None
    suggested_delay_seconds: float | None = None


class VerifierEvidence(BaseModel):
    """Reference to evidence that supports the verifier outcome."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    reference: str
    description: str | None = None


class VerifierResult(BaseModel):
    """Structured verifier result for transcript and eval use."""

    model_config = ConfigDict(extra="forbid")

    status: VerifierStatus
    summary: str = Field(min_length=1)
    diagnostics: list[VerifierDiagnostic] = Field(default_factory=list)
    retry_hint: VerifierRetryHint | None = None
    evidence: list[VerifierEvidence] = Field(default_factory=list)
    synthetic_failure: SyntheticFailure | None = None


class Verifier(Protocol):
    """Stable verifier execution contract."""

    @property
    def definition(self) -> VerifierDefinition:
        """Return the verifier's static metadata."""

    async def verify(self, request: VerifierRequest) -> VerifierResult:
        """Run verification against the requested target."""
