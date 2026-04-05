from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path

from app.agent.loop import AgentLoop
from app.agent.llm_loop import LLMAgentLoop
from app.agent.memory import InMemorySessionStore
from app.agent.tools import ReadFileTool, ToolCallRecord, write_catalog


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentChatResult:
    session_id: str
    assistant_message: str
    tool_calls: list[ToolCallRecord]
    consulted_files: list[str]
    history: list["AgentConversationTurn"]


@dataclass(slots=True)
class AgentConversationTurn:
    role: str
    content: str
    consulted_files: list[str]
    tool_calls: list[ToolCallRecord]


class AgentService:
    def __init__(
        self,
        *,
        data_dir: Path,
        session_store: InMemorySessionStore | None = None,
        read_file_tool: ReadFileTool | None = None,
        loop: AgentLoop | LLMAgentLoop | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._session_store = session_store or InMemorySessionStore()
        self._read_file_tool = read_file_tool or ReadFileTool(data_dir)
        if loop is not None:
            self._loop = loop
        elif os.getenv("OPENAI_API_KEY"):
            try:
                self._loop = LLMAgentLoop(read_file_tool=self._read_file_tool)
            except RuntimeError as exc:
                logger.warning("Falling back to rule-based AgentLoop: %s", exc)
                self._loop = AgentLoop(read_file_tool=self._read_file_tool)
        else:
            self._loop = AgentLoop(read_file_tool=self._read_file_tool)

    def ensure_catalog(self) -> Path:
        return write_catalog(self._data_dir)

    def chat(self, *, session_id: str | None, message: str) -> AgentChatResult:
        session = self._session_store.get_or_create(session_id)
        self._session_store.append_turn(session.session_id, role="user", content=message)
        run_result = self._loop.run(message, history=session.turns)
        self._session_store.append_turn(
            session.session_id,
            role="assistant",
            content=run_result.assistant_message,
            consulted_files=run_result.consulted_files,
            tool_calls=run_result.tool_calls,
        )
        return AgentChatResult(
            session_id=session.session_id,
            assistant_message=run_result.assistant_message,
            tool_calls=run_result.tool_calls,
            consulted_files=run_result.consulted_files,
            history=self._snapshot_history(session.turns),
        )

    def get_history(self, *, session_id: str) -> list[AgentConversationTurn] | None:
        session = self._session_store.get(session_id)
        if session is None:
            return None
        return self._snapshot_history(session.turns)

    def _snapshot_history(self, turns) -> list[AgentConversationTurn]:
        history: list[AgentConversationTurn] = []
        for turn in turns:
            history.append(
                AgentConversationTurn(
                    role=turn.role,
                    content=turn.content,
                    consulted_files=list(turn.consulted_files),
                    tool_calls=[
                        ToolCallRecord(
                            tool_name=call.tool_name,
                            arguments=dict(call.arguments),
                            status=call.status,
                            output_preview=call.output_preview,
                        )
                        for call in turn.tool_calls
                    ],
                )
            )
        return history
