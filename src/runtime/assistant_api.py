"""Session-scoped assistant adapter over canonical runtime truth and derived context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from context.handoff import IncidentHandoffContextAssembler
from context.session_artifacts import SessionArtifactContext
from runtime.console_api import (
    ConsoleSessionDetail,
    ConsoleSessionTimelineResponse,
    ConsoleVerificationResult,
    ConsoleVerificationStatus,
    OperatorConsoleAPI,
)
from runtime.inspect import load_artifact_context

_DEFAULT_TIMELINE_LIMIT = 10
_MAX_TIMELINE_LIMIT = 20
_TIMELINE_LIMIT_PATTERN = re.compile(r"\blast\s+(?P<limit>\d{1,2})\b")


class AssistantIntent(StrEnum):
    """Bounded assistant intents supported by the Phase 1.5 session pane."""

    STATE_EXPLANATION = "state_explanation"
    TIMELINE_SUMMARY = "timeline_summary"
    BLOCKED_OR_READY = "blocked_or_ready"
    APPROVAL_COMPARISON = "approval_comparison"
    EVIDENCE_SUMMARY = "evidence_summary"
    VERIFIER_EXPLANATION = "verifier_explanation"
    HANDOFF_DRAFT = "handoff_draft"
    UNSUPPORTED = "unsupported"


class AssistantSourceKind(StrEnum):
    """Runtime or derived surfaces used to ground assistant responses."""

    CHECKPOINT = "checkpoint"
    TRANSCRIPT = "transcript"
    SESSION_ARTIFACT_CONTEXT = "session_artifact_context"
    WORKING_MEMORY = "working_memory"
    HANDOFF_ARTIFACT = "handoff_artifact"


class AssistantSourceReference(BaseModel):
    """One grounded source used to derive an assistant answer."""

    model_config = ConfigDict(extra="forbid")

    kind: AssistantSourceKind
    detail: str = Field(min_length=1)


class AssistantGrounding(BaseModel):
    """Explicit authority-vs-support boundary for one assistant answer."""

    model_config = ConfigDict(extra="forbid")

    workflow_authority: str = Field(
        default=(
            "Incident control and decision state are controlled by the current checkpoint, "
            "append-only transcripts, approval records, and verifier-backed artifacts "
            "reconstructed through SessionArtifactContext."
        ),
        min_length=1,
    )
    current_prompt_only: bool = True
    chat_history_persisted: bool = False
    authority_sources: list[AssistantSourceReference] = Field(default_factory=list)
    supporting_sources: list[AssistantSourceReference] = Field(default_factory=list)
    note: str = Field(
        default=(
            "This answer is derived from the current session runtime truth, with supporting "
            "derived context called out separately when used. Chat history is not persisted "
            "and does not control incident state, approval state, or recovery state."
        ),
        min_length=1,
    )


class SessionAssistantRequest(BaseModel):
    """One session-scoped assistant request."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)


class SessionAssistantResponse(BaseModel):
    """One bounded assistant response for the selected incident session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    intent: AssistantIntent
    answer: str = Field(min_length=1)
    grounding: AssistantGrounding
    suggested_prompts: list[str] = Field(default_factory=list)


def _normalize_prompt(prompt: str) -> str:
    return " ".join(prompt.strip().lower().split())


def _extract_timeline_limit(prompt: str) -> int:
    match = _TIMELINE_LIMIT_PATTERN.search(prompt)
    if match is None:
        return _DEFAULT_TIMELINE_LIMIT
    requested = int(match.group("limit"))
    return max(1, min(requested, _MAX_TIMELINE_LIMIT))


def _suggested_prompts() -> list[str]:
    return [
        "Why is this session blocked?",
        "Summarize the last 10 timeline entries.",
        "What evidence supports the current recommendation?",
        "What changes if I deny instead of approve?",
        "Explain the latest verifier result in plain English.",
        "Draft a handoff summary for the next operator.",
    ]


def _assistant_grounding(
    *,
    authority_sources: tuple[tuple[AssistantSourceKind, str], ...],
    supporting_sources: tuple[tuple[AssistantSourceKind, str], ...] = (),
) -> AssistantGrounding:
    return AssistantGrounding(
        authority_sources=[
            AssistantSourceReference(kind=kind, detail=detail)
            for kind, detail in authority_sources
        ],
        supporting_sources=[
            AssistantSourceReference(kind=kind, detail=detail)
            for kind, detail in supporting_sources
        ],
    )


@dataclass(slots=True)
class SessionAssistantAPI:
    """Deterministic assistant surface over one existing incident session."""

    checkpoint_root: Path = Path("sessions/checkpoints")
    transcript_root: Path = Path("sessions/transcripts")
    handoff_root: Path = Path("sessions/handoffs")

    @property
    def working_memory_root(self) -> Path:
        return self.checkpoint_root.parent / "working_memory"

    @property
    def console_api(self) -> OperatorConsoleAPI:
        return OperatorConsoleAPI(
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            handoff_root=self.handoff_root,
        )

    def respond(
        self,
        session_id: str,
        *,
        prompt: str,
    ) -> SessionAssistantResponse:
        normalized_prompt = _normalize_prompt(prompt)
        if not normalized_prompt:
            msg = "prompt must not be empty"
            raise ValueError(msg)

        detail = self.console_api.get_session_detail(session_id)
        verification = self.console_api.get_verification_result(session_id)
        handoff = self.console_api.get_handoff_artifact(session_id)
        context = load_artifact_context(
            session_id,
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            working_memory_root=self.working_memory_root,
        )

        intent = self._classify_prompt(normalized_prompt)
        if intent is AssistantIntent.TIMELINE_SUMMARY:
            timeline = self.console_api.get_session_timeline(
                session_id,
                limit=_extract_timeline_limit(normalized_prompt),
            )
            answer = self._timeline_summary(timeline)
            grounding = _assistant_grounding(
                authority_sources=(
                    (
                        AssistantSourceKind.TRANSCRIPT,
                        "Recent operator timeline entries are reconstructed "
                        "from transcript events.",
                    ),
                    (
                        AssistantSourceKind.CHECKPOINT,
                        "Session identity and current phase come from the current checkpoint.",
                    ),
                ),
            )
        elif intent is AssistantIntent.BLOCKED_OR_READY:
            answer = self._blocked_or_ready_explanation(detail, verification)
            grounding = _assistant_grounding(
                authority_sources=(
                    (
                        AssistantSourceKind.CHECKPOINT,
                        "Current phase, approval state, and requested/effective mode "
                        "come from the current checkpoint.",
                    ),
                    (
                        AssistantSourceKind.TRANSCRIPT,
                        "Latest verifier and approval activity come from "
                        "the append-only transcript.",
                    ),
                    (
                        AssistantSourceKind.SESSION_ARTIFACT_CONTEXT,
                        "Current evidence and next-action summaries come from "
                        "verifier-backed artifacts reconstructed through SessionArtifactContext.",
                    ),
                ),
            )
        elif intent is AssistantIntent.APPROVAL_COMPARISON:
            answer = self._approval_consequences(detail)
            grounding = _assistant_grounding(
                authority_sources=(
                    (
                        AssistantSourceKind.CHECKPOINT,
                        "Approval status and current phase come from the current checkpoint.",
                    ),
                    (
                        AssistantSourceKind.SESSION_ARTIFACT_CONTEXT,
                        "The bounded rollback candidate comes from the verified "
                        "action-stub artifact chain reconstructed through SessionArtifactContext.",
                    ),
                ),
            )
        elif intent is AssistantIntent.EVIDENCE_SUMMARY:
            answer = self._evidence_summary(context, detail)
            authority_sources: list[tuple[AssistantSourceKind, str]] = [
                (
                    AssistantSourceKind.SESSION_ARTIFACT_CONTEXT,
                    "Evidence, hypothesis, recommendation, and action-stub "
                    "artifacts are reconstructed through SessionArtifactContext.",
                ),
                (
                    AssistantSourceKind.TRANSCRIPT,
                    "Latest verifier summaries come from transcript verifier events.",
                ),
            ]
            supporting_sources: list[tuple[AssistantSourceKind, str]] = []
            if context.latest_incident_working_memory() is not None:
                supporting_sources.append(
                    (
                        AssistantSourceKind.WORKING_MEMORY,
                        "IncidentWorkingMemory provides a compact semantic snapshot that helps "
                        "summarize the current incident, but it does not control workflow state.",
                    )
                )
            grounding = _assistant_grounding(
                authority_sources=tuple(authority_sources),
                supporting_sources=tuple(supporting_sources),
            )
        elif intent is AssistantIntent.VERIFIER_EXPLANATION:
            answer = self._verifier_explanation(detail, verification)
            grounding = _assistant_grounding(
                authority_sources=(
                    (
                        AssistantSourceKind.TRANSCRIPT,
                        "Latest verifier status and summary come from transcript verifier events.",
                    ),
                    (
                        AssistantSourceKind.SESSION_ARTIFACT_CONTEXT,
                        "Outcome verification availability comes from reconstructed "
                        "verifier-backed artifacts.",
                    ),
                ),
            )
        elif intent is AssistantIntent.HANDOFF_DRAFT:
            answer = self._handoff_draft(context, detail, handoff.available)
            authority_sources = [
                (
                    AssistantSourceKind.CHECKPOINT,
                    "Current phase, progress, and approval state come from the checkpoint.",
                ),
                (
                    AssistantSourceKind.SESSION_ARTIFACT_CONTEXT,
                    "The handoff draft is derived from current reconstructed session artifacts.",
                ),
            ]
            supporting_sources: list[tuple[AssistantSourceKind, str]] = []
            if handoff.available:
                supporting_sources.append(
                    (
                        AssistantSourceKind.HANDOFF_ARTIFACT,
                        "An exported handoff artifact already exists for this incident and "
                        "provides operator-facing derived context, not workflow authority.",
                    )
                )
            if context.latest_incident_working_memory() is not None:
                supporting_sources.append(
                    (
                        AssistantSourceKind.WORKING_MEMORY,
                        "IncidentWorkingMemory contributes compact incident context but does "
                        "not control incident state or approval state.",
                    )
                )
            grounding = _assistant_grounding(
                authority_sources=tuple(authority_sources),
                supporting_sources=tuple(supporting_sources),
            )
        elif intent is AssistantIntent.UNSUPPORTED:
            answer = (
                "This assistant only explains the current session truth. Ask about current "
                "state, recent timeline activity, approval-vs-deny consequences, evidence, "
                "the latest verifier result, or a handoff-ready summary."
            )
            grounding = _assistant_grounding(
                authority_sources=(
                    (
                        AssistantSourceKind.CHECKPOINT,
                        "Session scope and current phase remain grounded in the checkpoint.",
                    ),
                ),
            )
        else:
            answer = self._state_explanation(detail)
            grounding = _assistant_grounding(
                authority_sources=(
                    (
                        AssistantSourceKind.CHECKPOINT,
                        "Session identity, phase, approval, and mode come "
                        "from the current checkpoint.",
                    ),
                    (
                        AssistantSourceKind.TRANSCRIPT,
                        "Latest verifier summary comes from the append-only transcript.",
                    ),
                    (
                        AssistantSourceKind.SESSION_ARTIFACT_CONTEXT,
                        "Evidence and next-action summaries come from verifier-backed artifacts "
                        "reconstructed through SessionArtifactContext.",
                    ),
                ),
            )

        return SessionAssistantResponse(
            session_id=detail.session_id,
            incident_id=detail.incident_id,
            intent=intent,
            answer=answer,
            grounding=grounding,
            suggested_prompts=_suggested_prompts(),
        )

    def _classify_prompt(self, prompt: str) -> AssistantIntent:
        if "handoff" in prompt or "next operator" in prompt:
            return AssistantIntent.HANDOFF_DRAFT
        if (
            "verifier" in prompt
            or "plain english" in prompt
            or "verification result" in prompt
        ):
            return AssistantIntent.VERIFIER_EXPLANATION
        if ("approve" in prompt and "deny" in prompt) or "deny instead" in prompt:
            return AssistantIntent.APPROVAL_COMPARISON
        if "timeline" in prompt or "recent activity" in prompt:
            return AssistantIntent.TIMELINE_SUMMARY
        if "evidence" in prompt or "supports the current recommendation" in prompt:
            return AssistantIntent.EVIDENCE_SUMMARY
        if "blocked" in prompt or "ready" in prompt:
            return AssistantIntent.BLOCKED_OR_READY
        if any(
            marker in prompt
            for marker in (
                "fix the incident",
                "decide what to do across incidents",
                "plan a remediation strategy",
                "what should we do next across all systems",
            )
        ):
            return AssistantIntent.UNSUPPORTED
        return AssistantIntent.STATE_EXPLANATION

    def _state_explanation(self, detail: ConsoleSessionDetail) -> str:
        mode_text = (
            detail.requested_mode.value
            if detail.requested_mode is detail.effective_mode
            else (
                f"{detail.requested_mode.value}, currently degraded to "
                f"{detail.effective_mode.value}"
            )
        )
        answer = (
            f"Session {detail.session_id} for incident {detail.incident_id} is currently in "
            f"phase {detail.current_phase}. The session is running in {mode_text} mode. "
            f"Approval status is {detail.approval.status.value}. "
            f"Next action: {detail.next_recommended_action} "
            f"Current evidence summary: {detail.current_evidence_summary} "
            f"Latest verifier summary: {detail.latest_verifier_summary}"
        )
        if detail.mode_reason is not None:
            answer += f" Downgrade reason: {detail.mode_reason}."
        return answer

    def _blocked_or_ready_explanation(
        self,
        detail: ConsoleSessionDetail,
        verification: ConsoleVerificationResult,
    ) -> str:
        if (
            detail.current_phase == "action_stub_pending_approval"
            and detail.approval.status.value == "pending"
        ):
            explanation = (
                "This session is blocked on explicit human approval. The runtime has a "
                "bounded rollback candidate, but it will not execute while approval is still "
                "pending."
            )
            if detail.mode_reason is not None:
                explanation += f" The requested mode was downgraded because {detail.mode_reason}."
            explanation += f" Next action: {detail.next_recommended_action}"
            return explanation
        if detail.current_phase in {
            "action_stub_not_actionable",
            "follow_up_complete_no_action",
        }:
            return (
                "This session is not blocked on approval. It is currently conservative and "
                "non-actionable because the runtime does not have sufficient grounds for a "
                f"rollback candidate. Evidence summary: {detail.current_evidence_summary}"
            )
        if detail.current_phase == "action_stub_denied":
            return (
                "This session is blocked from write execution because the rollback candidate "
                "was denied. No rollback will run unless fresh verified evidence reopens a "
                "later action candidate. "
                f"Next action: {detail.next_recommended_action}"
            )
        if detail.current_phase == "action_execution_completed":
            return (
                "This session is ready for verification. The bounded rollback execution has "
                "completed, and the next step is to verify recovery from external runtime state."
            )
        if verification.status is ConsoleVerificationStatus.VERIFIED:
            return (
                "This session is not blocked. Recovery is already verifier-backed from "
                "external runtime state, so the operator can export handoff or continue "
                "monitoring."
            )
        return (
            "This session is not currently at the approval boundary. "
            f"Current phase: {detail.current_phase}. Next action: {detail.next_recommended_action}"
        )

    def _timeline_summary(self, timeline: ConsoleSessionTimelineResponse) -> str:
        if not timeline.entries:
            return "No recent operator-facing timeline entries are available for this session."
        lines = [
            f"Recent timeline activity for session {timeline.session_id}:",
        ]
        for entry in timeline.entries:
            lines.append(
                f"- {entry.timestamp.isoformat(timespec='seconds')}: {entry.summary}"
            )
        return "\n".join(lines)

    def _approval_consequences(self, detail: ConsoleSessionDetail) -> str:
        if detail.current_phase == "action_stub_pending_approval":
            return (
                "If you approve, the existing deployment-regression live surface will record "
                "approval, execute the bounded rollback candidate, and then run outcome "
                "verification. If you deny, the runtime will record a durable denial reason, "
                "skip rollback execution, and keep the session in a denied non-executing state."
            )
        if detail.approval.status.value == "approved":
            return (
                "Approval has already been recorded for this session, so the approve-vs-deny "
                "branch has already been resolved. The rollback path that followed is the one "
                "already reflected in durable session state."
            )
        if detail.approval.status.value == "denied":
            return (
                "Denial has already been recorded for this session, so no rollback execution "
                "will occur unless fresh verified evidence later creates a new approval-gated "
                "candidate."
            )
        return (
            "This session is not currently waiting on an approval decision. The approval "
            "comparison only applies when the runtime is at the pending rollback-candidate "
            "boundary."
        )

    def _evidence_summary(
        self,
        context: SessionArtifactContext,
        detail: ConsoleSessionDetail,
    ) -> str:
        del detail
        evidence = context.latest_verified_evidence_output().artifact
        hypothesis = context.latest_verified_hypothesis_output().artifact
        recommendation = context.latest_verified_recommendation_output().artifact
        working_memory = context.latest_incident_working_memory()

        if evidence is None:
            fallback = (
                working_memory.compact_handoff_note
                if working_memory is not None
                else "No verifier-backed evidence record is available yet."
            )
            return f"Current evidence summary: {fallback}"

        key_observations = ", ".join(evidence.observations[:2])
        parts = [
            f"Verified evidence summary: {evidence.evidence_summary}",
            f"Key observations: {key_observations}.",
        ]
        if hypothesis is not None:
            parts.append(f"Hypothesis rationale: {hypothesis.rationale_summary}")
        if recommendation is not None:
            parts.append(
                "Current recommendation summary: "
                f"{recommendation.action_summary}"
            )
        return " ".join(parts)

    def _verifier_explanation(
        self,
        detail: ConsoleSessionDetail,
        verification: ConsoleVerificationResult,
    ) -> str:
        if (
            verification.status is ConsoleVerificationStatus.VERIFIED
            and verification.output is not None
        ):
            output = verification.output
            return (
                "The latest verifier-backed runtime probe says recovery is currently verified. "
                f"In plain English: {output.service} is on version {output.current_version}, "
                f"health status is {output.health_status}, error rate is {output.error_rate:.2f}, "
                f"and timeout rate is {output.timeout_rate:.2f}."
            )
        if verification.status is ConsoleVerificationStatus.FAILED:
            return (
                "The latest outcome-verification path failed. "
                f"Verifier summary: {verification.summary}"
            )
        return (
            "There is no verifier-passed outcome verification artifact yet. "
            f"Current phase: {detail.current_phase}. Latest verifier summary: "
            f"{detail.latest_verifier_summary}"
        )

    def _handoff_draft(
        self,
        context: SessionArtifactContext,
        detail: ConsoleSessionDetail,
        handoff_available: bool,
    ) -> str:
        assembler = IncidentHandoffContextAssembler()
        handoff_context = assembler.assemble(context)
        availability_note = (
            "A durable handoff artifact already exists for this incident."
            if handoff_available
            else (
                "This is a draft derived from current runtime truth; export "
                "handoff to write the durable artifact."
            )
        )
        leading_hypothesis = (
            handoff_context.leading_hypothesis_summary or "Not yet available"
        )
        recommendation_summary = (
            handoff_context.recommendation_summary
            or detail.next_recommended_action
        )
        approval_summary = (
            handoff_context.approval.summary
            or handoff_context.approval.status.value
        )
        lines = [
            f"Handoff draft for {handoff_context.service or detail.incident_id}:",
            f"- Current phase: {handoff_context.current_phase}",
            f"- Progress: {handoff_context.progress_summary}",
            f"- Leading hypothesis: {leading_hypothesis}",
            f"- Recommendation: {recommendation_summary}",
            f"- Approval: {approval_summary}",
            f"- Attention point: {handoff_context.current_operator_attention_point}",
            f"- Note: {handoff_context.compact_handoff_note}",
            availability_note,
        ]
        return "\n".join(lines)
