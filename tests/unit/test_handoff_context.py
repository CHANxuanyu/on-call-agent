from pathlib import Path

import pytest
from pydantic import ValidationError

from context.handoff import (
    ApprovalHandoffSummary,
    HandoffArtifactReference,
    HandoffArtifactSource,
    IncidentHandoffContext,
)
from memory.checkpoints import ApprovalStatus


def test_handoff_context_requires_non_empty_attention_point() -> None:
    with pytest.raises(ValidationError):
        IncidentHandoffContext(
            incident_id="incident-handoff",
            service="payments-api",
            current_phase="recommendation_supported",
            progress_summary="Recommendation step completed.",
            approval=ApprovalHandoffSummary(status=ApprovalStatus.NONE),
            current_operator_attention_point="",
            compact_handoff_note="Recommendation is available for operator review.",
            derived_from=[
                HandoffArtifactReference(
                    source=HandoffArtifactSource.CHECKPOINT,
                    artifact_name="session_checkpoint",
                    path=Path("sessions/checkpoints/example.json"),
                )
            ],
        )


def test_handoff_context_requires_durable_references() -> None:
    with pytest.raises(ValidationError):
        IncidentHandoffContext(
            incident_id="incident-handoff",
            service="payments-api",
            current_phase="recommendation_supported",
            progress_summary="Recommendation step completed.",
            approval=ApprovalHandoffSummary(status=ApprovalStatus.NONE),
            current_operator_attention_point="Review the recommendation.",
            compact_handoff_note="Recommendation is available for operator review.",
            derived_from=[],
        )
