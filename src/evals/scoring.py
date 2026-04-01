"""Scorecard models for eval reporting."""

from __future__ import annotations

from pydantic import BaseModel


class EvalScoreCard(BaseModel):
    """Headline metrics for a scenario or suite result."""

    task_success: bool
    verifier_pass_rate: float
    unsafe_action_rate: float
    mean_steps_to_resolution: float | None = None
