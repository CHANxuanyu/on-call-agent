"""Typed models for scenario-based evaluation."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class EvalScenario(BaseModel):
    """Declarative scenario input for the eval harness."""

    scenario_id: str
    description: str
    fixture_path: Path | None = None
    expected_verifiers: list[str] = Field(default_factory=list)


class EvalResult(BaseModel):
    """Structured outcome for a single eval scenario."""

    scenario_id: str
    success: bool
    verifier_pass_rate: float | None = None
    notes: list[str] = Field(default_factory=list)
