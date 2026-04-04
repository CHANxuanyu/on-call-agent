from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from memory.incident_working_memory import (
    IncidentWorkingMemory,
    JsonIncidentWorkingMemoryStore,
    LeadingHypothesisSnapshot,
    RecommendationSnapshot,
    incident_working_memory_path,
)
from tools.implementations.incident_hypothesis import HypothesisType
from tools.implementations.incident_recommendation import (
    RecommendationApprovalLevel,
    RecommendationType,
)


def _memory_snapshot() -> IncidentWorkingMemory:
    return IncidentWorkingMemory(
        incident_id="incident-123",
        service="payments-api",
        source_session_id="session-123",
        source_checkpoint_id="checkpoint-123",
        source_phase="recommendation_supported",
        last_updated_by_step="incident_recommendation",
        last_updated_at=datetime(2026, 4, 1, tzinfo=UTC),
        leading_hypothesis=LeadingHypothesisSnapshot(
            hypothesis_type=HypothesisType.DEPLOYMENT_REGRESSION,
            summary="Deployment evidence supports a regression hypothesis.",
            evidence_supported=True,
        ),
        unresolved_gaps=["Need rollback confirmation from the on-call lead."],
        important_evidence_references=[
            "evidence:deployment-record-2026-04-01",
            "hypothesis:deployment_regression",
        ],
        recommendation=RecommendationSnapshot(
            recommendation_type=RecommendationType.VALIDATE_RECENT_DEPLOYMENT,
            summary="Validate the recent deployment path before any mitigation work.",
            required_approval_level=RecommendationApprovalLevel.ONCALL_LEAD,
            more_investigation_required=True,
        ),
        compact_handoff_note=(
            "Current verified hypothesis is deployment_regression and the next "
            "recommendation remains advisory."
        ),
    )


def test_incident_working_memory_rejects_empty_handoff_note() -> None:
    with pytest.raises(ValidationError):
        IncidentWorkingMemory(
            incident_id="incident-123",
            service="payments-api",
            source_session_id="session-123",
            source_checkpoint_id="checkpoint-123",
            source_phase="hypothesis_supported",
            last_updated_by_step="incident_hypothesis",
            compact_handoff_note="",
        )


def test_incident_working_memory_path_uses_deterministic_incident_filename(
    tmp_path: Path,
) -> None:
    path = incident_working_memory_path("incident/123", root=tmp_path)

    assert path == tmp_path / "incident__123.json"


def test_json_incident_working_memory_store_round_trips_snapshot(
    tmp_path: Path,
) -> None:
    memory = _memory_snapshot()
    store = JsonIncidentWorkingMemoryStore.for_incident(memory.incident_id, root=tmp_path)

    assert store.load_optional() is None

    written_path = store.write(memory)
    loaded_memory = store.load()

    assert written_path == tmp_path / "incident-123.json"
    assert loaded_memory == memory
