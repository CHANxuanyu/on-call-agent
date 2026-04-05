from __future__ import annotations

from dataclasses import dataclass, field
import uuid

from app.agent.tools import ToolCallRecord


@dataclass(slots=True)
class ConversationTurn:
    role: str
    content: str
    consulted_files: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


@dataclass(slots=True)
class ConversationSession:
    session_id: str
    turns: list[ConversationTurn] = field(default_factory=list)


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def get(self, session_id: str) -> ConversationSession | None:
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: str | None = None) -> ConversationSession:
        resolved_session_id = session_id or uuid.uuid4().hex
        session = self._sessions.get(resolved_session_id)
        if session is None:
            session = ConversationSession(session_id=resolved_session_id)
            self._sessions[resolved_session_id] = session
        return session

    def append_turn(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        consulted_files: list[str] | None = None,
        tool_calls: list[ToolCallRecord] | None = None,
    ) -> None:
        session = self.get_or_create(session_id)
        session.turns.append(
            ConversationTurn(
                role=role,
                content=content,
                consulted_files=list(consulted_files or []),
                tool_calls=[
                    ToolCallRecord(
                        tool_name=call.tool_name,
                        arguments=dict(call.arguments),
                        status=call.status,
                        output_preview=call.output_preview,
                    )
                    for call in (tool_calls or [])
                ],
            )
        )
