"""Thin stdlib-backed Operator Console server over existing runtime truth."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from runtime.assistant_api import SessionAssistantAPI, SessionAssistantRequest
from runtime.console_api import (
    ConsoleApprovalDecision,
    OperatorConsoleAPI,
)

_API_ROOT = "/api/phase1"


class ConsoleApprovalRequest(BaseModel):
    """JSON request body for approval or denial from the console UI."""

    model_config = ConfigDict(extra="forbid")

    decision: ConsoleApprovalDecision
    reason: str | None = None


class ConsoleErrorPayload(BaseModel):
    """Structured JSON error payload for the thin console server."""

    model_config = ConfigDict(extra="forbid")

    error: str = Field(min_length=1)


def _write_json_response(
    handler: BaseHTTPRequestHandler,
    *,
    status: HTTPStatus,
    payload: BaseModel | dict[str, Any],
) -> None:
    body = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    encoded = json.dumps(body, sort_keys=True).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _write_html_response(
    handler: BaseHTTPRequestHandler,
    *,
    status: HTTPStatus,
    html: str,
) -> None:
    encoded = html.encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def render_operator_console_html() -> str:
    """Return the minimal panel-first Operator Console HTML page."""

    return _CONSOLE_PAGE_TEMPLATE.replace("__API_ROOT__", _API_ROOT)


def _console_handler(server: OperatorConsoleServer) -> type[BaseHTTPRequestHandler]:
    class ConsoleRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            split = urlsplit(self.path)
            try:
                if split.path in {"/", "/index.html"}:
                    _write_html_response(
                        self,
                        status=HTTPStatus.OK,
                        html=render_operator_console_html(),
                    )
                    return
                if split.path == f"{_API_ROOT}/sessions":
                    limit = _parse_optional_limit(split.query)
                    _write_json_response(
                        self,
                        status=HTTPStatus.OK,
                        payload=server.console_api.list_sessions(limit=limit),
                    )
                    return

                session_id, suffix = _session_route_parts(split.path)
                if session_id is None:
                    _write_json_response(
                        self,
                        status=HTTPStatus.NOT_FOUND,
                        payload=ConsoleErrorPayload(
                            error=f"unknown path: {split.path}"
                        ),
                    )
                    return
                if suffix == ():
                    _write_json_response(
                        self,
                        status=HTTPStatus.OK,
                        payload=server.console_api.get_session_detail(session_id),
                    )
                    return
                if suffix == ("timeline",):
                    limit = _parse_optional_limit(split.query, default=20)
                    _write_json_response(
                        self,
                        status=HTTPStatus.OK,
                        payload=server.console_api.get_session_timeline(
                            session_id,
                            limit=limit,
                        ),
                    )
                    return
                if suffix == ("verification",):
                    _write_json_response(
                        self,
                        status=HTTPStatus.OK,
                        payload=server.console_api.get_verification_result(session_id),
                    )
                    return
                if suffix == ("handoff",):
                    _write_json_response(
                        self,
                        status=HTTPStatus.OK,
                        payload=server.console_api.get_handoff_artifact(session_id),
                    )
                    return
                _write_json_response(
                    self,
                    status=HTTPStatus.NOT_FOUND,
                    payload=ConsoleErrorPayload(error=f"unknown path: {split.path}"),
                )
            except FileNotFoundError as exc:
                _write_json_response(
                    self,
                    status=HTTPStatus.NOT_FOUND,
                    payload=ConsoleErrorPayload(error=str(exc)),
                )
            except (OSError, ValidationError, ValueError) as exc:
                _write_json_response(
                    self,
                    status=HTTPStatus.BAD_REQUEST,
                    payload=ConsoleErrorPayload(error=str(exc)),
                )

        def do_POST(self) -> None:  # noqa: N802
            split = urlsplit(self.path)
            try:
                session_id, suffix = _session_route_parts(split.path)
                if session_id is None:
                    _write_json_response(
                        self,
                        status=HTTPStatus.NOT_FOUND,
                        payload=ConsoleErrorPayload(
                            error=f"unknown path: {split.path}"
                        ),
                    )
                    return
                if suffix == ("approval",):
                    payload = ConsoleApprovalRequest.model_validate(_read_json_body(self))
                    _write_json_response(
                        self,
                        status=HTTPStatus.OK,
                        payload=server.console_api.resolve_approval(
                            session_id,
                            decision=payload.decision,
                            reason=payload.reason,
                        ),
                    )
                    return
                if suffix == ("verification",):
                    _write_json_response(
                        self,
                        status=HTTPStatus.OK,
                        payload=server.console_api.rerun_verification(session_id),
                    )
                    return
                if suffix == ("handoff", "export"):
                    _write_json_response(
                        self,
                        status=HTTPStatus.OK,
                        payload=server.console_api.export_handoff_artifact(session_id),
                    )
                    return
                if suffix == ("assistant",):
                    payload = SessionAssistantRequest.model_validate(_read_json_body(self))
                    _write_json_response(
                        self,
                        status=HTTPStatus.OK,
                        payload=server.assistant_api.respond(
                            session_id,
                            prompt=payload.prompt,
                        ),
                    )
                    return
                _write_json_response(
                    self,
                    status=HTTPStatus.NOT_FOUND,
                    payload=ConsoleErrorPayload(error=f"unknown path: {split.path}"),
                )
            except FileNotFoundError as exc:
                _write_json_response(
                    self,
                    status=HTTPStatus.NOT_FOUND,
                    payload=ConsoleErrorPayload(error=str(exc)),
                )
            except (OSError, ValidationError, ValueError) as exc:
                _write_json_response(
                    self,
                    status=HTTPStatus.BAD_REQUEST,
                    payload=ConsoleErrorPayload(error=str(exc)),
                )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

    return ConsoleRequestHandler


def _parse_optional_limit(query: str, *, default: int | None = None) -> int | None:
    values = parse_qs(query).get("limit")
    if not values:
        return default
    return int(values[0])


def _session_route_parts(path: str) -> tuple[str | None, tuple[str, ...]]:
    prefix = f"{_API_ROOT}/sessions/"
    if not path.startswith(prefix):
        return None, ()
    remainder = path.removeprefix(prefix).strip("/")
    if not remainder:
        return None, ()
    parts = tuple(part for part in remainder.split("/") if part)
    if not parts:
        return None, ()
    return parts[0], parts[1:]


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_length = int(handler.headers.get("Content-Length", "0"))
    raw_body = handler.rfile.read(content_length) if content_length else b"{}"
    if not raw_body:
        return {}
    return json.loads(raw_body.decode("utf-8"))


@dataclass(slots=True)
class OperatorConsoleServer:
    """Local panel-first Operator Console server over existing runtime seams."""

    host: str = "127.0.0.1"
    port: int = 8080
    checkpoint_root: Path = Path("sessions/checkpoints")
    transcript_root: Path = Path("sessions/transcripts")
    handoff_root: Path = Path("sessions/handoffs")
    console_api: OperatorConsoleAPI = field(init=False)
    assistant_api: SessionAssistantAPI = field(init=False)
    _server: ThreadingHTTPServer = field(init=False)
    _thread: Thread | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.console_api = OperatorConsoleAPI(
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            handoff_root=self.handoff_root,
        )
        self.assistant_api = SessionAssistantAPI(
            checkpoint_root=self.checkpoint_root,
            transcript_root=self.transcript_root,
            handoff_root=self.handoff_root,
        )
        self._server = ThreadingHTTPServer(
            (self.host, self.port),
            _console_handler(self),
        )

    @property
    def bound_port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.bound_port}"

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.1)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def __enter__(self) -> OperatorConsoleServer:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


_CONSOLE_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>On-Call Copilot Operator Console</title>
  <style>
    :root {
      --bg: #f4f0e8;
      --panel: #fffdf8;
      --border: #d7ccbb;
      --text: #1e2328;
      --muted: #6a6f73;
      --accent: #8a3b12;
      --accent-soft: #f8e3d8;
      --success: #275d38;
      --warn: #8c5a16;
      --danger: #8a1d16;
      --shadow: 0 12px 30px rgba(56, 43, 24, 0.08);
      --mono: "IBM Plex Mono", "SFMono-Regular", ui-monospace, monospace;
      --sans: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #efe4d3 0%, var(--bg) 100%);
      color: var(--text);
      font-family: var(--sans);
    }
    header {
      padding: 1.2rem 1.4rem;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 253, 248, 0.9);
      position: sticky;
      top: 0;
      backdrop-filter: blur(10px);
      z-index: 1;
    }
    header h1 {
      margin: 0 0 0.35rem 0;
      font-size: 1.45rem;
    }
    header p {
      margin: 0;
      max-width: 70rem;
      color: var(--muted);
      line-height: 1.4;
    }
    .layout {
      display: grid;
      grid-template-columns: 18rem minmax(0, 1fr) 24rem;
      gap: 1rem;
      padding: 1rem;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel h2, .panel h3 {
      margin: 0;
      font-size: 1rem;
    }
    .panel-header {
      padding: 0.9rem 1rem;
      border-bottom: 1px solid var(--border);
      background: rgba(248, 227, 216, 0.5);
    }
    .panel-body {
      padding: 1rem;
    }
    .sessions-list {
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }
    .session-card {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: #fff;
      padding: 0.8rem;
      text-align: left;
      cursor: pointer;
    }
    .session-card.active {
      border-color: var(--accent);
      background: var(--accent-soft);
    }
    .session-card strong, .kpi strong {
      display: block;
      font-family: var(--mono);
      font-size: 0.88rem;
    }
    .session-meta, .muted, .assistant-note {
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.35;
    }
    .main-column {
      display: grid;
      gap: 1rem;
    }
    .status-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.8rem;
    }
    .kpi {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.8rem;
      background: #fff;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      align-items: center;
      margin-top: 0.8rem;
    }
    button {
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      padding: 0.55rem 0.85rem;
      border-radius: 999px;
      cursor: pointer;
      font: inherit;
    }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff9f2;
    }
    button.warn {
      border-color: var(--warn);
      color: var(--warn);
    }
    button.danger {
      border-color: var(--danger);
      color: var(--danger);
    }
    textarea, input {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.75rem;
      font: inherit;
      background: #fff;
      color: var(--text);
    }
    textarea {
      min-height: 7rem;
      resize: vertical;
    }
    .timeline {
      display: flex;
      flex-direction: column;
      gap: 0.7rem;
    }
    .timeline-entry {
      border-left: 3px solid var(--accent);
      padding-left: 0.8rem;
    }
    .timeline-entry time, code, pre {
      font-family: var(--mono);
      font-size: 0.85rem;
    }
    .assistant-pane {
      position: sticky;
      top: 6.2rem;
    }
    .messages {
      display: flex;
      flex-direction: column;
      gap: 0.8rem;
      max-height: 48rem;
      overflow: auto;
      margin-bottom: 0.8rem;
    }
    .message {
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 0.8rem;
      background: #fff;
    }
    .message.user {
      background: #f7efe3;
    }
    .message strong {
      display: block;
      margin-bottom: 0.4rem;
    }
    .message pre {
      margin: 0;
      white-space: pre-wrap;
    }
    .chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      margin-bottom: 0.8rem;
    }
    .chip {
      border: 1px solid var(--border);
      background: #fff;
      border-radius: 999px;
      padding: 0.35rem 0.6rem;
      cursor: pointer;
      font-size: 0.85rem;
    }
    .empty-state {
      padding: 1rem;
      color: var(--muted);
    }
    @media (max-width: 1180px) {
      .layout {
        grid-template-columns: 16rem minmax(0, 1fr);
      }
      .assistant-pane {
        grid-column: 1 / -1;
        position: static;
      }
    }
    @media (max-width: 820px) {
      .layout {
        grid-template-columns: 1fr;
      }
      .status-grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>On-Call Copilot Operator Console</h1>
    <p>
      Panel-first operator workspace over existing runtime truth. The assistant pane is
      session-scoped and secondary: it explains current checkpoint, transcript, verifier, and
      handoff state, but it does not become workflow authority.
    </p>
  </header>
  <main class="layout">
    <section class="panel" aria-label="Recent sessions">
      <div class="panel-header">
        <h2>Sessions</h2>
      </div>
      <div class="panel-body">
        <div id="sessions-list" class="sessions-list"></div>
      </div>
    </section>

    <section class="main-column">
      <section class="panel" aria-label="Session detail">
        <div class="panel-header">
          <h2>Incident Detail</h2>
        </div>
        <div id="detail-panel" class="panel-body">
          <div class="empty-state">Select a session to load current incident detail.</div>
        </div>
      </section>

      <section class="panel" aria-label="Recent timeline">
        <div class="panel-header">
          <h2>Timeline</h2>
        </div>
        <div id="timeline-panel" class="panel-body">
          <div class="empty-state">Timeline activity will appear once a session is selected.</div>
        </div>
      </section>
    </section>

    <aside class="panel assistant-pane" aria-label="Session assistant">
      <div class="panel-header">
        <h2>Session Assistant</h2>
      </div>
      <div class="panel-body">
        <p class="assistant-note">
          Ask about the selected session. The assistant uses current runtime truth only. It does
          not persist chat history and it does not control approval or recovery state.
        </p>
        <div id="assistant-prompts" class="chip-row"></div>
        <div id="assistant-messages" class="messages">
          <div class="message">
            <strong>Assistant</strong>
            <pre>Select a session and ask about current state, evidence,
verifier results, approval consequences, timeline activity, or a
handoff draft.</pre>
          </div>
        </div>
        <textarea id="assistant-input" placeholder="Why is this session blocked?"></textarea>
        <div class="actions">
          <button id="assistant-send" class="primary" type="button">Ask Session Assistant</button>
        </div>
      </div>
    </aside>
  </main>

  <script>
    const API_ROOT = "__API_ROOT__";
    const sessionsList = document.getElementById("sessions-list");
    const detailPanel = document.getElementById("detail-panel");
    const timelinePanel = document.getElementById("timeline-panel");
    const assistantMessages = document.getElementById("assistant-messages");
    const assistantInput = document.getElementById("assistant-input");
    const assistantSend = document.getElementById("assistant-send");
    const assistantPrompts = document.getElementById("assistant-prompts");

    let selectedSessionId = null;

    const promptExamples = [
      "Why is this session blocked?",
      "Summarize the last 10 timeline entries.",
      "What evidence supports the current recommendation?",
      "What changes if I deny instead of approve?",
      "Explain the latest verifier result in plain English.",
      "Draft a handoff summary for the next operator."
    ];

    function appendMessage(role, text) {
      const wrapper = document.createElement("div");
      wrapper.className = `message ${role}`;
      const title = document.createElement("strong");
      title.textContent = role === "user" ? "Operator" : "Assistant";
      const pre = document.createElement("pre");
      pre.textContent = text;
      wrapper.append(title, pre);
      assistantMessages.appendChild(wrapper);
      assistantMessages.scrollTop = assistantMessages.scrollHeight;
    }

    function resetAssistantPane() {
      assistantMessages.innerHTML = "";
      appendMessage(
        "assistant",
        "Ask about the selected session. This pane explains existing "
        + "runtime truth and does not store chat history."
      );
    }

    async function fetchJson(url, options = {}) {
      const response = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || `Request failed: ${response.status}`);
      }
      return payload;
    }

    function escapeHtml(value) {
      const text = value === null || value === undefined ? "" : String(value);
      return text
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function renderPromptExamples() {
      assistantPrompts.innerHTML = "";
      for (const prompt of promptExamples) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "chip";
        button.textContent = prompt;
        button.addEventListener("click", () => {
          assistantInput.value = prompt;
        });
        assistantPrompts.appendChild(button);
      }
    }

    function renderSessions(sessions) {
      sessionsList.innerHTML = "";
      if (sessions.length === 0) {
        sessionsList.innerHTML =
          `<div class="empty-state">No sessions found in the configured checkpoint root.</div>`;
        return;
      }
      for (const session of sessions) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "session-card";
        if (session.session_id === selectedSessionId) {
          button.classList.add("active");
        }
        button.innerHTML = `
          <strong>${escapeHtml(session.session_id)}</strong>
          <div class="session-meta">
            incident=${escapeHtml(session.incident_id)}<br>
            phase=${escapeHtml(session.current_phase)}<br>
            mode=${escapeHtml(session.requested_mode)}${
              session.requested_mode === session.effective_mode
                ? ""
                : ` -> ${escapeHtml(session.effective_mode)}`
            }<br>
            approval=${escapeHtml(session.approval_status)}<br>
            verifier=${escapeHtml(session.latest_verifier_summary)}<br>
            updated=${escapeHtml(session.last_updated)}
          </div>
        `;
        button.addEventListener("click", () => selectSession(session.session_id));
        sessionsList.appendChild(button);
      }
    }

    function renderDetail(detail, verification) {
      detailPanel.innerHTML = `
        <div class="status-grid">
          <div class="kpi">
            <strong>${escapeHtml(detail.session_id)}</strong>
            <div class="muted">
              incident=${escapeHtml(detail.incident_id)}
              family=${escapeHtml(detail.family)}
            </div>
          </div>
          <div class="kpi">
            <strong>${escapeHtml(detail.current_phase)}</strong>
            <div class="muted">
              step=${escapeHtml(detail.current_step)}
              updated=${escapeHtml(detail.latest_checkpoint_time)}
            </div>
          </div>
          <div class="kpi">
            <strong>requested=${escapeHtml(detail.requested_mode)}</strong>
            <div class="muted">
              effective=${escapeHtml(detail.effective_mode)}${
                detail.mode_reason
                  ? `<br>downgrade=${escapeHtml(detail.mode_reason)}`
                  : ""
              }
            </div>
          </div>
          <div class="kpi">
            <strong>approval=${escapeHtml(detail.approval.status)}</strong>
            <div class="muted">
              ${escapeHtml(detail.approval.requested_action || "no pending action")}
            </div>
          </div>
          <div class="kpi">
            <strong>Next Action</strong>
            <div class="muted">${escapeHtml(detail.next_recommended_action)}</div>
          </div>
          <div class="kpi">
            <strong>Verifier</strong>
            <div class="muted">${escapeHtml(detail.latest_verifier_summary)}</div>
          </div>
          <div class="kpi">
            <strong>Evidence</strong>
            <div class="muted">${escapeHtml(detail.current_evidence_summary)}</div>
          </div>
          <div class="kpi">
            <strong>Verification</strong>
            <div class="muted">${escapeHtml(verification.summary)}</div>
          </div>
        </div>
        <div class="actions">
          <input
            id="action-reason"
            type="text"
            placeholder="Operator reason for approve/deny/export actions"
          >
          <button id="approve-button" class="primary" type="button">Approve</button>
          <button id="deny-button" class="danger" type="button">Deny</button>
          <button id="verify-button" class="warn" type="button">Verify</button>
          <button id="handoff-button" type="button">Export Handoff</button>
        </div>
        <p class="muted" style="margin-top: 0.8rem;">
          Handoff: ${
            detail.handoff.available
              ? `available at ${escapeHtml(detail.handoff.handoff_path)}`
              : "not exported yet"
          }
        </p>
      `;

      document
        .getElementById("approve-button")
        .addEventListener("click", () => resolveApproval("approve"));
      document
        .getElementById("deny-button")
        .addEventListener("click", () => resolveApproval("deny"));
      document.getElementById("verify-button").addEventListener("click", rerunVerification);
      document.getElementById("handoff-button").addEventListener("click", exportHandoff);
    }

    function renderTimeline(timeline) {
      if (timeline.entries.length === 0) {
        timelinePanel.innerHTML =
          `<div class="empty-state">No recent operator-facing timeline entries are
available.</div>`;
        return;
      }
      const entries = timeline.entries.map((entry) => `
        <div class="timeline-entry">
          <div><code>${escapeHtml(entry.timestamp)}</code></div>
          <div>
            <strong>${escapeHtml(entry.kind)}</strong>
            ${escapeHtml(entry.summary)}
          </div>
        </div>
      `).join("");
      timelinePanel.innerHTML = `<div class="timeline">${entries}</div>`;
    }

    async function loadSessions() {
      const payload = await fetchJson(`${API_ROOT}/sessions?limit=20`);
      renderSessions(payload.sessions);
      if (!selectedSessionId && payload.sessions.length > 0) {
        await selectSession(payload.sessions[0].session_id);
      }
    }

    async function selectSession(sessionId) {
      selectedSessionId = sessionId;
      renderSessions((await fetchJson(`${API_ROOT}/sessions?limit=20`)).sessions);
      resetAssistantPane();
      const [detail, timeline, verification] = await Promise.all([
        fetchJson(`${API_ROOT}/sessions/${sessionId}`),
        fetchJson(`${API_ROOT}/sessions/${sessionId}/timeline?limit=12`),
        fetchJson(`${API_ROOT}/sessions/${sessionId}/verification`)
      ]);
      renderDetail(detail, verification);
      renderTimeline(timeline);
    }

    function currentReason() {
      const input = document.getElementById("action-reason");
      return input && input.value.trim() ? input.value.trim() : null;
    }

    async function resolveApproval(decision) {
      if (!selectedSessionId) return;
      const defaultReason = decision === "approve"
        ? "Approved from the Operator Console."
        : "Denied from the Operator Console.";
      await fetchJson(`${API_ROOT}/sessions/${selectedSessionId}/approval`, {
        method: "POST",
        body: JSON.stringify({ decision, reason: currentReason() || defaultReason }),
      });
      await selectSession(selectedSessionId);
    }

    async function rerunVerification() {
      if (!selectedSessionId) return;
      await fetchJson(`${API_ROOT}/sessions/${selectedSessionId}/verification`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await selectSession(selectedSessionId);
    }

    async function exportHandoff() {
      if (!selectedSessionId) return;
      await fetchJson(`${API_ROOT}/sessions/${selectedSessionId}/handoff/export`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await selectSession(selectedSessionId);
    }

    async function askAssistant() {
      if (!selectedSessionId) {
        appendMessage("assistant", "Select a session first so the assistant stays session-scoped.");
        return;
      }
      const prompt = assistantInput.value.trim();
      if (!prompt) {
        appendMessage("assistant", "Enter a prompt about the selected session.");
        return;
      }
      appendMessage("user", prompt);
      assistantInput.value = "";
      const payload = await fetchJson(`${API_ROOT}/sessions/${selectedSessionId}/assistant`, {
        method: "POST",
        body: JSON.stringify({ prompt }),
      });
      const authoritySources = payload.grounding.authority_sources
        .map((source) => `${source.kind}: ${source.detail}`)
        .join("\\n");
      const supportingSources = payload.grounding.supporting_sources
        .map((source) => `${source.kind}: ${source.detail}`)
        .join("\\n");
      const authorityBlock = authoritySources
        ? `\\n\\nWorkflow authority:\\n${authoritySources}`
        : "";
      const supportingBlock = supportingSources
        ? `\\n\\nSupporting context:\\n${supportingSources}`
        : "";
      appendMessage(
        "assistant",
        `${payload.answer}\\n\\nGrounding: ${payload.grounding.note}` +
          `${authorityBlock}${supportingBlock}`
      );
    }

    assistantSend.addEventListener("click", askAssistant);
    assistantInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
        askAssistant();
      }
    });

    renderPromptExamples();
    loadSessions().catch((error) => {
      detailPanel.innerHTML =
        `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    });
  </script>
</body>
</html>
"""
