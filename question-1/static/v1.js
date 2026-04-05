const form = document.getElementById("search-form");
const queryInput = document.getElementById("search-query");
const resultsList = document.getElementById("results-list");
const emptyState = document.getElementById("empty-state");
const resultsCount = document.getElementById("results-count");

if (form && queryInput && resultsList && emptyState && resultsCount) {
    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        const query = queryInput.value.trim();
        const nextUrl = query ? `/v1?q=${encodeURIComponent(query)}` : "/v1";
        window.history.replaceState({}, "", nextUrl);

        if (!query) {
            renderResults([]);
            return;
        }

        const response = await fetch(`/v1/search?q=${encodeURIComponent(query)}`);
        if (!response.ok) {
            renderResults([]);
            emptyState.textContent = "Search failed. Please try again.";
            emptyState.classList.remove("hidden");
            return;
        }

        const payload = await response.json();
        renderResults(payload.results);
    });
}

function renderResults(results) {
    resultsCount.textContent = String(results.length);
    resultsList.innerHTML = results
        .map((result) => {
            return `
                <li class="result-card">
                    <div class="result-head">
                        <h2>${escapeHtml(result.title)}</h2>
                        <span class="score">score ${Number(result.score).toFixed(3)}</span>
                    </div>
                    <p class="result-id">${escapeHtml(result.id)}</p>
                    <p class="snippet">${escapeHtml(result.snippet)}</p>
                </li>
            `;
        })
        .join("");

    if (results.length === 0) {
        emptyState.textContent = "No matching documents found.";
        emptyState.classList.remove("hidden");
        return;
    }

    emptyState.classList.add("hidden");
}

function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
