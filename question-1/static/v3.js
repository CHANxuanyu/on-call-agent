const chatForm = document.getElementById("chat-form");
const apiKeyInput = document.getElementById("api-key");
const chatInput = document.getElementById("chat-message");
const resetChatButton = document.getElementById("reset-chat");
const chatSubmitButton = document.getElementById("chat-submit");
const chatStatus = document.getElementById("chat-status");
const sessionIdNode = document.getElementById("session-id");
const conversationHistory = document.getElementById("conversation-history");
const historyEmpty = document.getElementById("history-empty");
const toolTraceList = document.getElementById("tool-trace");
const traceEmpty = document.getElementById("trace-empty");
const consultedFilesList = document.getElementById("consulted-files");
const filesEmpty = document.getElementById("files-empty");

const SESSION_STORAGE_KEY = "oncall-agent.v3.session-id";
const API_KEY_STORAGE_KEY = "oncall-agent.v3.api-key";

let sessionId = null;
let isSending = false;

if (
    chatForm &&
    apiKeyInput &&
    chatInput &&
    resetChatButton &&
    chatSubmitButton &&
    chatStatus &&
    sessionIdNode &&
    conversationHistory &&
    historyEmpty &&
    toolTraceList &&
    traceEmpty &&
    consultedFilesList &&
    filesEmpty
) {
    void bootstrapChatPage();
    apiKeyInput.addEventListener("input", persistApiKey);
    resetChatButton.addEventListener("click", () => {
        resetConversation({ keepApiKey: true });
    });
    chatForm.addEventListener("submit", handleChatSubmit);
}

async function bootstrapChatPage() {
    apiKeyInput.value = readStorage(API_KEY_STORAGE_KEY) || "";
    sessionId = readStorage(SESSION_STORAGE_KEY);
    syncSessionBadge();
    renderSession([]);

    if (!sessionId) {
        return;
    }

    try {
        const response = await fetch(`/v3/history/${encodeURIComponent(sessionId)}`, {
            headers: buildAuthHeaders(),
        });
        const payload = await parseJson(response);

        if (response.status === 404) {
            resetConversation({
                keepApiKey: true,
                message: "Previous session was not found. Started a new chat.",
                tone: "info",
            });
            return;
        }

        if (!response.ok) {
            showStatus(buildErrorMessage(response.status, payload, "Failed to restore the previous session."), "error");
            return;
        }

        renderSession(payload.history || []);
    } catch (error) {
        showStatus(`Failed to restore the previous session. ${stringifyError(error)}`, "error");
    }
}

async function handleChatSubmit(event) {
    event.preventDefault();
    if (isSending) {
        return;
    }

    const message = chatInput.value.trim();
    if (!message) {
        return;
    }

    persistApiKey();
    setSubmitting(true);
    hideStatus();

    try {
        const response = await fetch("/v3/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                ...buildAuthHeaders(),
            },
            body: JSON.stringify({
                session_id: sessionId,
                message,
            }),
        });
        const payload = await parseJson(response);

        if (!response.ok) {
            showStatus(buildErrorMessage(response.status, payload, "Agent request failed. Please try again."), "error");
            return;
        }

        sessionId = payload.session_id || null;
        if (sessionId) {
            writeStorage(SESSION_STORAGE_KEY, sessionId);
        }
        syncSessionBadge();
        renderSession(payload.history || []);
        chatInput.value = "";
        chatInput.focus();
    } catch (error) {
        showStatus(`Agent request failed. ${stringifyError(error)}`, "error");
    } finally {
        setSubmitting(false);
    }
}

function renderSession(history) {
    renderConversation(history);
    renderLatestAssistantTurn(getLatestAssistantTurn(history));
}

function renderConversation(history) {
    conversationHistory.innerHTML = history
        .map((turn) => {
            const role = turn.role === "assistant" ? "assistant" : "user";
            const label = role === "assistant" ? "Assistant" : "You";
            const files = Array.isArray(turn.consulted_files) ? turn.consulted_files : [];
            return `
                <li class="chat-turn ${role}">
                    <div class="chat-turn-head">
                        <span class="chat-role">${escapeHtml(label)}</span>
                    </div>
                    <div class="chat-bubble ${role}">
                        ${renderTurnContent(turn)}
                        ${renderTurnFiles(files)}
                    </div>
                </li>
            `;
        })
        .join("");
    historyEmpty.classList.toggle("hidden", history.length > 0);
}

function renderTurnContent(turn) {
    if (turn.role === "assistant") {
        return renderAssistantMessage(turn.content || "");
    }
    return renderPlainMessage(turn.content || "");
}

function renderAssistantMessage(message) {
    const sections = parseAssistantSections(message);
    const hasStructuredItems = sections.some((section) => section.items.length > 0);
    if (sections.length === 0 || !hasStructuredItems) {
        return renderPlainMessage(message || "No response.");
    }

    return sections
        .map((section) => {
            const items = section.items
                .map((item) => `<li>${escapeHtml(item)}</li>`)
                .join("");
            return `
                <section class="assistant-section chat-section">
                    <h3>${escapeHtml(section.title)}</h3>
                    <ul class="assistant-list">${items}</ul>
                </section>
            `;
        })
        .join("");
}

function renderPlainMessage(message) {
    const blocks = String(message)
        .split(/\n\s*\n/g)
        .map((block) => block.trim())
        .filter(Boolean);

    if (blocks.length === 0) {
        return '<p class="chat-text">No response.</p>';
    }

    return blocks
        .map((block) => `<p class="chat-text">${escapeHtml(block).replaceAll("\n", "<br>")}</p>`)
        .join("");
}

function renderTurnFiles(files) {
    if (!files.length) {
        return "";
    }

    return `
        <div class="chat-turn-files">
            ${files.map((fileName) => `<span class="inline-file-tag">${escapeHtml(fileName)}</span>`).join("")}
        </div>
    `;
}

function renderLatestAssistantTurn(turn) {
    if (!turn) {
        renderTrace([]);
        renderConsultedFiles([]);
        return;
    }

    renderTrace(turn.tool_calls || []);
    renderConsultedFiles(turn.consulted_files || []);
}

function renderTrace(toolCalls) {
    toolTraceList.innerHTML = toolCalls
        .map((call) => {
            const fileName = call.arguments && call.arguments.fname ? call.arguments.fname : "(none)";
            const preview = truncatePreview(call.output_preview || "", 110);
            return `
                <li class="trace-card">
                    <div class="trace-head">
                        <div class="trace-main">
                            <strong>${escapeHtml(call.tool_name)}</strong>
                            <span class="trace-file">${escapeHtml(fileName)}</span>
                        </div>
                        <span class="trace-status">${escapeHtml(call.status)}</span>
                    </div>
                    <p class="trace-preview" title="${escapeHtml(call.output_preview || "")}">${escapeHtml(preview)}</p>
                </li>
            `;
        })
        .join("");
    traceEmpty.classList.toggle("hidden", toolCalls.length > 0);
}

function renderConsultedFiles(files) {
    consultedFilesList.innerHTML = files
        .map((fileName) => `<li class="file-tag">${escapeHtml(fileName)}</li>`)
        .join("");
    filesEmpty.classList.toggle("hidden", files.length > 0);
}

function getLatestAssistantTurn(history) {
    for (let index = history.length - 1; index >= 0; index -= 1) {
        const turn = history[index];
        if (turn.role === "assistant") {
            return turn;
        }
    }
    return null;
}

function resetConversation(options = {}) {
    const { keepApiKey = true, message = "", tone = "info" } = options;

    sessionId = null;
    removeStorage(SESSION_STORAGE_KEY);
    syncSessionBadge();
    renderSession([]);
    chatInput.value = "";
    chatInput.focus();

    if (!keepApiKey) {
        apiKeyInput.value = "";
        removeStorage(API_KEY_STORAGE_KEY);
    }

    if (message) {
        showStatus(message, tone);
        return;
    }

    hideStatus();
}

function persistApiKey() {
    const apiKey = apiKeyInput.value.trim();
    if (apiKey) {
        writeStorage(API_KEY_STORAGE_KEY, apiKey);
        return;
    }
    removeStorage(API_KEY_STORAGE_KEY);
}

function buildAuthHeaders() {
    const apiKey = apiKeyInput.value.trim();
    if (!apiKey) {
        return {};
    }
    return { "X-API-Key": apiKey };
}

function syncSessionBadge() {
    sessionIdNode.textContent = sessionId || "not started";
}

function setSubmitting(submitting) {
    isSending = submitting;
    chatSubmitButton.disabled = submitting;
    resetChatButton.disabled = submitting;
    chatSubmitButton.textContent = submitting ? "Sending..." : "Send";
}

function showStatus(message, tone) {
    chatStatus.textContent = message;
    chatStatus.classList.remove("hidden", "error", "success", "info");
    if (tone) {
        chatStatus.classList.add(tone);
    }
}

function hideStatus() {
    chatStatus.textContent = "";
    chatStatus.classList.add("hidden");
    chatStatus.classList.remove("error", "success", "info");
}

async function parseJson(response) {
    const text = await response.text();
    if (!text) {
        return {};
    }
    try {
        return JSON.parse(text);
    } catch {
        return { detail: text };
    }
}

function buildErrorMessage(status, payload, fallbackMessage) {
    if (status === 401) {
        return "Unauthorized. Enter a valid X-API-Key and try again.";
    }
    if (status === 429) {
        return "Rate limit exceeded. Please wait a minute and try again.";
    }
    if (payload && typeof payload.detail === "string" && payload.detail.trim()) {
        return payload.detail;
    }
    return fallbackMessage;
}

function readStorage(key) {
    try {
        return window.sessionStorage.getItem(key);
    } catch {
        return null;
    }
}

function writeStorage(key, value) {
    try {
        window.sessionStorage.setItem(key, value);
    } catch {
        return;
    }
}

function removeStorage(key) {
    try {
        window.sessionStorage.removeItem(key);
    } catch {
        return;
    }
}

function stringifyError(error) {
    if (error instanceof Error && error.message) {
        return error.message;
    }
    return "Unexpected error.";
}

function parseAssistantSections(message) {
    return message
        .trim()
        .split(/\n\s*\n/g)
        .map((block) => {
            const lines = block
                .split("\n")
                .map((line) => line.trim())
                .filter(Boolean);
            if (lines.length === 0) {
                return null;
            }

            return {
                title: lines[0],
                items: lines.slice(1).map((line) => line.replace(/^-+\s*/, "")),
            };
        })
        .filter(Boolean);
}

function truncatePreview(value, limit) {
    if (value.length <= limit) {
        return value;
    }
    return `${value.slice(0, limit).trimEnd()}...`;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
