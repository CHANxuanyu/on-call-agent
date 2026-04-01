from pathlib import Path

import pytest

from tools.implementations.evidence_reading import EvidenceBundleReaderTool, EvidenceReadOutput
from tools.implementations.follow_up_investigation import (
    FollowUpInvestigationOutput,
    InvestigationTarget,
)
from tools.models import ToolCall, ToolResultStatus


@pytest.mark.asyncio
async def test_evidence_bundle_reader_returns_snapshot_for_selected_target() -> None:
    tool = EvidenceBundleReaderTool(
        fixtures_path=Path("evals/fixtures/evidence_snapshots.json")
    )
    investigation_output = FollowUpInvestigationOutput(
        incident_id="incident-400",
        service="payments-api",
        investigation_target=InvestigationTarget.RECENT_DEPLOYMENT,
        evidence_gap="Recent deployment context is unavailable.",
        rationale="Deployment context is the first missing input.",
        recommended_read_only_action="Inspect the latest deployment record for payments-api.",
    )

    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={"investigation_output": investigation_output.model_dump(mode="json")},
        )
    )

    evidence_output = EvidenceReadOutput.model_validate(result.output)

    assert result.status is ToolResultStatus.SUCCEEDED
    assert evidence_output.snapshot_id == "deployment-record-2026-04-01"
    assert evidence_output.investigation_target is InvestigationTarget.RECENT_DEPLOYMENT


@pytest.mark.asyncio
async def test_evidence_bundle_reader_fails_when_fixture_catalog_is_missing(
    tmp_path: Path,
) -> None:
    tool = EvidenceBundleReaderTool(fixtures_path=tmp_path / "missing.json")
    investigation_output = FollowUpInvestigationOutput(
        incident_id="incident-401",
        service="payments-api",
        investigation_target=InvestigationTarget.RUNBOOK,
        evidence_gap="Runbook reference is unavailable.",
        rationale="Need runbook guidance.",
        recommended_read_only_action="Review the runbook index for payments-api.",
    )

    result = await tool.execute(
        ToolCall(
            name=tool.definition.name,
            arguments={"investigation_output": investigation_output.model_dump(mode="json")},
        )
    )

    assert result.status is ToolResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.code == "missing_fixture"
