from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from context.handoff import (
    ApprovalHandoffSummary,
    HandoffArtifactReference,
    HandoffArtifactSource,
    IncidentHandoffContext,
)
from context.handoff_artifact import (
    IncidentHandoffArtifact,
    JsonIncidentHandoffArtifactStore,
    incident_handoff_artifact_path,
)
from memory.checkpoints import ApprovalStatus


def _sample_handoff_context() -> IncidentHandoffContext:
    return IncidentHandoffContext(
        incident_id="incident-handoff-artifact",
        service="payments-api",
        current_phase="recommendation_supported",
        progress_summary="Recommendation step produced a validated advisory next step.",
        leading_hypothesis_summary="Evidence supports a recent deployment regression.",
        recommendation_summary="Validate the recent deployment path for payments-api.",
        unresolved_gaps=["Need rollback safety confirmation before action."],
        important_evidence_references=[
            "evidence:deployment-record-2026-04-01",
            "hypothesis:deployment_regression",
        ],
        approval=ApprovalHandoffSummary(
            status=ApprovalStatus.NONE,
            summary="No approval is pending yet.",
        ),
        current_operator_attention_point=(
            "Validate the recent deployment path for payments-api."
        ),
        compact_handoff_note="Current recommendation is validate_recent_deployment.",
        derived_from=[
            HandoffArtifactReference(
                source=HandoffArtifactSource.CHECKPOINT,
                artifact_name="session_checkpoint",
                path=Path("sessions/checkpoints/example.json"),
                detail="session-example-checkpoint",
            )
        ],
    )


def test_handoff_artifact_requires_non_empty_checkpoint_id() -> None:
    with pytest.raises(ValidationError):
        IncidentHandoffArtifact(
            source_session_id="session-example",
            source_checkpoint_id="",
            source_checkpoint_time=datetime.now(UTC),
            handoff=_sample_handoff_context(),
        )


def test_handoff_artifact_path_uses_deterministic_incident_filename(
    tmp_path: Path,
) -> None:
    path = incident_handoff_artifact_path("incident/123", root=tmp_path)
    assert path == tmp_path / "incident__123.json"


def test_json_handoff_artifact_store_round_trips_and_is_deterministic(
    tmp_path: Path,
) -> None:
    artifact = IncidentHandoffArtifact(
        source_session_id="session-example",
        source_checkpoint_id="session-example-checkpoint",
        source_checkpoint_time=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        handoff=_sample_handoff_context(),
    )
    store = JsonIncidentHandoffArtifactStore.for_incident(
        "incident-handoff-artifact",
        root=tmp_path,
    )

    first_path = store.write(artifact)
    first_contents = first_path.read_text(encoding="utf-8")
    second_path = store.write(artifact)
    second_contents = second_path.read_text(encoding="utf-8")

    assert second_path == first_path
    assert second_contents == first_contents
    assert store.load() == artifact
