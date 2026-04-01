"""Runner contract for scenario-based evaluation."""

from __future__ import annotations

from typing import Protocol

from evals.models import EvalResult, EvalScenario


class EvalRunner(Protocol):
    """Runs a scenario and returns a structured result."""

    async def run(self, scenario: EvalScenario) -> EvalResult:
        """Execute one eval scenario."""
