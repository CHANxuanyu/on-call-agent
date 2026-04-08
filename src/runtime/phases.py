"""Central bounded incident phase vocabulary and boundary helpers."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class IncidentPhase(StrEnum):
    """Currently implemented durable phase literals for the incident runtime."""

    TRIAGE_COMPLETED = "triage_completed"
    TRIAGE_FAILED_VERIFICATION = "triage_failed_verification"
    TRIAGE_UNVERIFIED = "triage_unverified"
    FOLLOW_UP_INVESTIGATION_SELECTED = "follow_up_investigation_selected"
    FOLLOW_UP_COMPLETE_NO_ACTION = "follow_up_complete_no_action"
    FOLLOW_UP_UNVERIFIED = "follow_up_unverified"
    FOLLOW_UP_FAILED_VERIFICATION = "follow_up_failed_verification"
    EVIDENCE_READING_COMPLETED = "evidence_reading_completed"
    EVIDENCE_READING_NOT_APPLICABLE = "evidence_reading_not_applicable"
    EVIDENCE_READING_DEFERRED = "evidence_reading_deferred"
    EVIDENCE_READING_UNVERIFIED = "evidence_reading_unverified"
    EVIDENCE_READING_FAILED_VERIFICATION = "evidence_reading_failed_verification"
    EVIDENCE_READING_FAILED_ARTIFACTS = "evidence_reading_failed_artifacts"
    HYPOTHESIS_SUPPORTED = "hypothesis_supported"
    HYPOTHESIS_INSUFFICIENT_EVIDENCE = "hypothesis_insufficient_evidence"
    HYPOTHESIS_DEFERRED = "hypothesis_deferred"
    HYPOTHESIS_UNVERIFIED = "hypothesis_unverified"
    HYPOTHESIS_FAILED_VERIFICATION = "hypothesis_failed_verification"
    HYPOTHESIS_FAILED_ARTIFACTS = "hypothesis_failed_artifacts"
    RECOMMENDATION_SUPPORTED = "recommendation_supported"
    RECOMMENDATION_CONSERVATIVE = "recommendation_conservative"
    RECOMMENDATION_DEFERRED = "recommendation_deferred"
    RECOMMENDATION_UNVERIFIED = "recommendation_unverified"
    RECOMMENDATION_FAILED_VERIFICATION = "recommendation_failed_verification"
    RECOMMENDATION_FAILED_ARTIFACTS = "recommendation_failed_artifacts"
    ACTION_STUB_PENDING_APPROVAL = "action_stub_pending_approval"
    ACTION_STUB_NOT_ACTIONABLE = "action_stub_not_actionable"
    ACTION_STUB_DEFERRED = "action_stub_deferred"
    ACTION_STUB_UNVERIFIED = "action_stub_unverified"
    ACTION_STUB_FAILED_VERIFICATION = "action_stub_failed_verification"
    ACTION_STUB_FAILED_ARTIFACTS = "action_stub_failed_artifacts"
    ACTION_STUB_APPROVED = "action_stub_approved"
    ACTION_STUB_DENIED = "action_stub_denied"
    ACTION_EXECUTION_COMPLETED = "action_execution_completed"
    ACTION_EXECUTION_DEFERRED = "action_execution_deferred"
    ACTION_EXECUTION_UNVERIFIED = "action_execution_unverified"
    ACTION_EXECUTION_FAILED_VERIFICATION = "action_execution_failed_verification"
    ACTION_EXECUTION_FAILED_ARTIFACTS = "action_execution_failed_artifacts"
    OUTCOME_VERIFICATION_SUCCEEDED = "outcome_verification_succeeded"
    OUTCOME_VERIFICATION_UNVERIFIED = "outcome_verification_unverified"
    OUTCOME_VERIFICATION_FAILED_VERIFICATION = (
        "outcome_verification_failed_verification"
    )
    OUTCOME_VERIFICATION_FAILED_ARTIFACTS = "outcome_verification_failed_artifacts"


class IncidentPhaseFamily(StrEnum):
    """High-level phase families used for boundary checks and summaries."""

    TRIAGE = "triage"
    FOLLOW_UP = "follow_up"
    EVIDENCE_READING = "evidence_reading"
    HYPOTHESIS = "hypothesis"
    RECOMMENDATION = "recommendation"
    ACTION_STUB = "action_stub"
    ACTION_EXECUTION = "action_execution"
    OUTCOME_VERIFICATION = "outcome_verification"


TRIAGE_PHASES = frozenset(
    {
        IncidentPhase.TRIAGE_COMPLETED,
        IncidentPhase.TRIAGE_FAILED_VERIFICATION,
        IncidentPhase.TRIAGE_UNVERIFIED,
    }
)
FOLLOW_UP_PHASES = frozenset(
    {
        IncidentPhase.FOLLOW_UP_INVESTIGATION_SELECTED,
        IncidentPhase.FOLLOW_UP_COMPLETE_NO_ACTION,
        IncidentPhase.FOLLOW_UP_UNVERIFIED,
        IncidentPhase.FOLLOW_UP_FAILED_VERIFICATION,
    }
)
EVIDENCE_READING_PHASES = frozenset(
    {
        IncidentPhase.EVIDENCE_READING_COMPLETED,
        IncidentPhase.EVIDENCE_READING_NOT_APPLICABLE,
        IncidentPhase.EVIDENCE_READING_DEFERRED,
        IncidentPhase.EVIDENCE_READING_UNVERIFIED,
        IncidentPhase.EVIDENCE_READING_FAILED_VERIFICATION,
        IncidentPhase.EVIDENCE_READING_FAILED_ARTIFACTS,
    }
)
HYPOTHESIS_PHASES = frozenset(
    {
        IncidentPhase.HYPOTHESIS_SUPPORTED,
        IncidentPhase.HYPOTHESIS_INSUFFICIENT_EVIDENCE,
        IncidentPhase.HYPOTHESIS_DEFERRED,
        IncidentPhase.HYPOTHESIS_UNVERIFIED,
        IncidentPhase.HYPOTHESIS_FAILED_VERIFICATION,
        IncidentPhase.HYPOTHESIS_FAILED_ARTIFACTS,
    }
)
RECOMMENDATION_PHASES = frozenset(
    {
        IncidentPhase.RECOMMENDATION_SUPPORTED,
        IncidentPhase.RECOMMENDATION_CONSERVATIVE,
        IncidentPhase.RECOMMENDATION_DEFERRED,
        IncidentPhase.RECOMMENDATION_UNVERIFIED,
        IncidentPhase.RECOMMENDATION_FAILED_VERIFICATION,
        IncidentPhase.RECOMMENDATION_FAILED_ARTIFACTS,
    }
)
ACTION_STUB_PHASES = frozenset(
    {
        IncidentPhase.ACTION_STUB_PENDING_APPROVAL,
        IncidentPhase.ACTION_STUB_NOT_ACTIONABLE,
        IncidentPhase.ACTION_STUB_DEFERRED,
        IncidentPhase.ACTION_STUB_UNVERIFIED,
        IncidentPhase.ACTION_STUB_FAILED_VERIFICATION,
        IncidentPhase.ACTION_STUB_FAILED_ARTIFACTS,
        IncidentPhase.ACTION_STUB_APPROVED,
        IncidentPhase.ACTION_STUB_DENIED,
    }
)
ACTION_EXECUTION_PHASES = frozenset(
    {
        IncidentPhase.ACTION_EXECUTION_COMPLETED,
        IncidentPhase.ACTION_EXECUTION_DEFERRED,
        IncidentPhase.ACTION_EXECUTION_UNVERIFIED,
        IncidentPhase.ACTION_EXECUTION_FAILED_VERIFICATION,
        IncidentPhase.ACTION_EXECUTION_FAILED_ARTIFACTS,
    }
)
OUTCOME_VERIFICATION_PHASES = frozenset(
    {
        IncidentPhase.OUTCOME_VERIFICATION_SUCCEEDED,
        IncidentPhase.OUTCOME_VERIFICATION_UNVERIFIED,
        IncidentPhase.OUTCOME_VERIFICATION_FAILED_VERIFICATION,
        IncidentPhase.OUTCOME_VERIFICATION_FAILED_ARTIFACTS,
    }
)

EVIDENCE_VERIFIER_PHASES = FOLLOW_UP_PHASES
HYPOTHESIS_VERIFIER_PHASES = EVIDENCE_READING_PHASES
RECOMMENDATION_VERIFIER_PHASES = HYPOTHESIS_PHASES
ACTION_STUB_VERIFIER_PHASES = RECOMMENDATION_PHASES

FOLLOW_UP_STEP_ENTRY_PHASES = TRIAGE_PHASES
EVIDENCE_STEP_ENTRY_PHASES = FOLLOW_UP_PHASES
HYPOTHESIS_STEP_ENTRY_PHASES = EVIDENCE_READING_PHASES
RECOMMENDATION_STEP_ENTRY_PHASES = HYPOTHESIS_PHASES
ACTION_STUB_STEP_ENTRY_PHASES = RECOMMENDATION_PHASES
ROLLBACK_EXECUTION_STEP_ENTRY_PHASES = ACTION_STUB_PHASES
OUTCOME_VERIFICATION_STEP_ENTRY_PHASES = frozenset(
    {*ACTION_EXECUTION_PHASES, *OUTCOME_VERIFICATION_PHASES}
)
APPROVAL_RESOLUTION_ENTRY_PHASES = frozenset(
    {IncidentPhase.ACTION_STUB_PENDING_APPROVAL}
)

FOLLOW_UP_TARGET_COMPATIBLE_PHASES = frozenset(
    {IncidentPhase.FOLLOW_UP_INVESTIGATION_SELECTED}
)
EVIDENCE_COMPATIBLE_PHASES = frozenset({IncidentPhase.EVIDENCE_READING_COMPLETED})
HYPOTHESIS_COMPATIBLE_PHASES = frozenset(
    {
        IncidentPhase.HYPOTHESIS_SUPPORTED,
        IncidentPhase.HYPOTHESIS_INSUFFICIENT_EVIDENCE,
    }
)
RECOMMENDATION_COMPATIBLE_PHASES = frozenset(
    {
        IncidentPhase.RECOMMENDATION_SUPPORTED,
        IncidentPhase.RECOMMENDATION_CONSERVATIVE,
    }
)
ACTION_EXECUTION_ARTIFACT_COMPATIBLE_PHASES = frozenset(
    {
        IncidentPhase.ACTION_EXECUTION_COMPLETED,
        IncidentPhase.OUTCOME_VERIFICATION_SUCCEEDED,
        IncidentPhase.OUTCOME_VERIFICATION_FAILED_VERIFICATION,
        IncidentPhase.OUTCOME_VERIFICATION_UNVERIFIED,
        IncidentPhase.OUTCOME_VERIFICATION_FAILED_ARTIFACTS,
    }
)
OUTCOME_VERIFICATION_ARTIFACT_COMPATIBLE_PHASES = frozenset(
    {
        IncidentPhase.OUTCOME_VERIFICATION_SUCCEEDED,
        IncidentPhase.OUTCOME_VERIFICATION_FAILED_VERIFICATION,
        IncidentPhase.OUTCOME_VERIFICATION_UNVERIFIED,
        IncidentPhase.OUTCOME_VERIFICATION_FAILED_ARTIFACTS,
    }
)

FAILURE_PHASES = frozenset(
    {
        IncidentPhase.TRIAGE_FAILED_VERIFICATION,
        IncidentPhase.FOLLOW_UP_FAILED_VERIFICATION,
        IncidentPhase.EVIDENCE_READING_FAILED_VERIFICATION,
        IncidentPhase.EVIDENCE_READING_FAILED_ARTIFACTS,
        IncidentPhase.HYPOTHESIS_FAILED_VERIFICATION,
        IncidentPhase.HYPOTHESIS_FAILED_ARTIFACTS,
        IncidentPhase.RECOMMENDATION_FAILED_VERIFICATION,
        IncidentPhase.RECOMMENDATION_FAILED_ARTIFACTS,
        IncidentPhase.ACTION_STUB_FAILED_VERIFICATION,
        IncidentPhase.ACTION_STUB_FAILED_ARTIFACTS,
        IncidentPhase.ACTION_EXECUTION_FAILED_VERIFICATION,
        IncidentPhase.ACTION_EXECUTION_FAILED_ARTIFACTS,
        IncidentPhase.OUTCOME_VERIFICATION_FAILED_VERIFICATION,
        IncidentPhase.OUTCOME_VERIFICATION_FAILED_ARTIFACTS,
    }
)
CONSERVATIVE_PATH_PHASES = frozenset(
    {
        IncidentPhase.HYPOTHESIS_INSUFFICIENT_EVIDENCE,
        IncidentPhase.RECOMMENDATION_CONSERVATIVE,
        IncidentPhase.ACTION_STUB_NOT_ACTIONABLE,
    }
)
SUPPORTED_PATH_PHASES = frozenset(
    {
        IncidentPhase.RECOMMENDATION_SUPPORTED,
        IncidentPhase.ACTION_STUB_PENDING_APPROVAL,
    }
)

_PHASE_FAMILY: dict[IncidentPhase, IncidentPhaseFamily] = {
    phase: IncidentPhaseFamily.TRIAGE for phase in TRIAGE_PHASES
} | {
    phase: IncidentPhaseFamily.FOLLOW_UP for phase in FOLLOW_UP_PHASES
} | {
    phase: IncidentPhaseFamily.EVIDENCE_READING for phase in EVIDENCE_READING_PHASES
} | {
    phase: IncidentPhaseFamily.HYPOTHESIS for phase in HYPOTHESIS_PHASES
} | {
    phase: IncidentPhaseFamily.RECOMMENDATION for phase in RECOMMENDATION_PHASES
} | {
    phase: IncidentPhaseFamily.ACTION_STUB for phase in ACTION_STUB_PHASES
} | {
    phase: IncidentPhaseFamily.ACTION_EXECUTION for phase in ACTION_EXECUTION_PHASES
} | {
    phase: IncidentPhaseFamily.OUTCOME_VERIFICATION
    for phase in OUTCOME_VERIFICATION_PHASES
}


def phase_family(phase: IncidentPhase) -> IncidentPhaseFamily:
    """Return the high-level family for one valid incident phase."""

    return _PHASE_FAMILY[phase]


def final_stage_for_phase(phase: IncidentPhase) -> str:
    """Return the operator-facing eval stage label for one valid phase."""

    family = phase_family(phase)
    if family is IncidentPhaseFamily.EVIDENCE_READING:
        return "evidence"
    return family.value


def phase_values(phases: Iterable[IncidentPhase]) -> tuple[str, ...]:
    """Render one ordered set of durable phase literal values."""

    return tuple(sorted(phase.value for phase in phases))


def require_phase_membership(
    *,
    phase: IncidentPhase,
    allowed_phases: frozenset[IncidentPhase],
    boundary_name: str,
    phase_label: str,
) -> IncidentPhase:
    """Reject globally valid but boundary-incompatible phases explicitly."""

    if phase in allowed_phases:
        return phase

    allowed = ", ".join(phase_values(allowed_phases))
    msg = (
        f"{boundary_name} does not accept {phase_label} '{phase.value}'. "
        f"Allowed phases: {allowed}."
    )
    raise ValueError(msg)
