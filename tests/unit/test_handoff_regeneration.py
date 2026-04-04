from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from context.handoff import (
    ApprovalHandoffSummary,
    HandoffArtifactReference,
    HandoffArtifactSource,
    IncidentHandoffContext,
    IncidentHandoffContextAssembler,
)
from context.handoff_artifact import IncidentHandoffArtifactWriter
from context.handoff_regeneration import (
    HandoffArtifactRegenerationStatus,
    IncidentHandoffArtifactRegenerator,
)
from context.session_artifacts import (
    ArtifactInsufficiency,
    ArtifactInsufficiencyCode,
    ArtifactKey,
    ArtifactResolution,
)
from memory.checkpoints import ApprovalStatus


def _sample_handoff_context() -> IncidentHandoffContext:
    return IncidentHandoffContext(
        incident_id="incident-handoff-regeneration",
        service="payments-api",
        current_phase="recommendation_supported",
        progress_summary="Recommendation step completed successfully.",
        leading_hypothesis_summary="Evidence supports a deployment regression.",
        recommendation_summary="Validate the recent deployment path for payments-api.",
        unresolved_gaps=["Need rollback safety confirmation."],
        important_evidence_references=["evidence:deployment-record-2026-04-01"],
        approval=ApprovalHandoffSummary(status=ApprovalStatus.NONE),
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


def _fake_artifact_context() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="session-handoff-regeneration",
        checkpoint_path=Path("sessions/checkpoints/session-handoff-regeneration.json"),
        transcript_path=Path("sessions/transcripts/session-handoff-regeneration.jsonl"),
        working_memory_path=Path(
            "sessions/working_memory/incident-handoff-regeneration.json"
        ),
        checkpoint=SimpleNamespace(
            incident_id="incident-handoff-regeneration",
            checkpoint_id="session-handoff-regeneration-checkpoint",
            latest_checkpoint_time=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
            current_phase="recommendation_supported",
        ),
        has_incident_working_memory=lambda: True,
    )


class _SpyAssembler:
    def __init__(self) -> None:
        self.called = False
        self.received_context: object | None = None

    def assemble(self, artifact_context: object) -> IncidentHandoffContext:
        self.called = True
        self.received_context = artifact_context
        return _sample_handoff_context()


class _SpyWriter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.called = False
        self.received_context: object | None = None
        self.received_handoff: IncidentHandoffContext | None = None

    def write(
        self,
        *,
        artifact_context: object,
        handoff_context: IncidentHandoffContext,
    ) -> Path:
        self.called = True
        self.received_context = artifact_context
        self.received_handoff = handoff_context
        return self.root / "incident-handoff-regeneration.json"


def test_regenerator_uses_assembler_and_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_context = _fake_artifact_context()
    spy_assembler = _SpyAssembler()
    spy_writer = _SpyWriter(root=Path("sessions/handoffs"))
    regenerator = IncidentHandoffArtifactRegenerator(
        assembler=cast(IncidentHandoffContextAssembler, spy_assembler),
        writer=cast(IncidentHandoffArtifactWriter, spy_writer),
    )

    monkeypatch.setattr(
        "context.handoff_regeneration.SessionArtifactContext.load",
        lambda *args, **kwargs: fake_context,
    )
    monkeypatch.setattr(
        IncidentHandoffArtifactRegenerator,
        "_required_artifact_resolution",
        lambda self, artifact_context: None,
    )

    result = regenerator.regenerate("session-handoff-regeneration")

    assert result.status is HandoffArtifactRegenerationStatus.WRITTEN
    assert result.handoff_path == Path(
        "sessions/handoffs/incident-handoff-regeneration.json"
    )
    assert spy_assembler.called
    assert spy_writer.called
    assert spy_assembler.received_context is fake_context
    assert spy_writer.received_context is fake_context
    assert spy_writer.received_handoff == result.handoff_context


def test_regenerator_reports_insufficiency_and_skips_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_context = _fake_artifact_context()
    spy_writer = _SpyWriter(root=Path("sessions/handoffs"))
    regenerator = IncidentHandoffArtifactRegenerator(
        writer=cast(IncidentHandoffArtifactWriter, spy_writer)
    )

    monkeypatch.setattr(
        "context.handoff_regeneration.SessionArtifactContext.load",
        lambda *args, **kwargs: fake_context,
    )
    monkeypatch.setattr(
        IncidentHandoffArtifactRegenerator,
        "_required_artifact_resolution",
        lambda self, artifact_context: (
            "recommendation",
            ArtifactResolution(
                artifact=None,
                insufficiency=ArtifactInsufficiency(
                    artifact=ArtifactKey.RECOMMENDATION,
                    code=ArtifactInsufficiencyCode.VERIFIER_NOT_PASSED,
                    message="Recommendation verifier has not passed yet.",
                    current_phase="recommendation_supported",
                    tool_name="incident_recommendation_builder",
                    verifier_name="incident_recommendation_outcome",
                ),
            ),
        ),
    )

    result = regenerator.regenerate("session-handoff-regeneration")

    assert result.status is HandoffArtifactRegenerationStatus.INSUFFICIENT
    assert result.required_artifact == "recommendation"
    assert result.insufficiency_reason == "Recommendation verifier has not passed yet."
    assert result.handoff_path is None
    assert not spy_writer.called
