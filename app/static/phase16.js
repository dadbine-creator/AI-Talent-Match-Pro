/* ============================================================
   PHASE 16 — LINKEDIN SOURCING ENGINE
   Frontend controller — connects to Flask backend
   ============================================================ */

/* ---------------------------------------------------------
   16.1 — LINKEDIN STATUS CHECK
   Checks if HR is connected to LinkedIn on load
--------------------------------------------------------- */
async function checkLinkedInStatus() {
    try {
        const res = await fetch("/linkedin/user");
        const data = await res.json();

        const bar = document.getElementById("linkedinStatusBar");
        if (!bar) return;

        if (data.connected) {
            bar.classList.add("connected");
            bar.querySelector(".linkedin-status-dot").classList.add("connected");
            bar.querySelector(".linkedin-status-text").textContent = `Connected as ${data.name}`;
            bar.querySelector(".linkedin-status-text").classList.add("connected");
            bar.querySelector(".linkedin-connect-btn").textContent = "Disconnect";
            bar.querySelector(".linkedin-connect-btn").classList.add("connected");
            bar.querySelector(".linkedin-connect-btn").onclick = linkedInDisconnect;
        } else {
            bar.querySelector(".linkedin-status-text").textContent = "Not connected to LinkedIn";
            bar.querySelector(".linkedin-connect-btn").textContent = "Connect LinkedIn";
            bar.querySelector(".linkedin-connect-btn").onclick = linkedInConnect;
        }
    } catch {
        // non-critical
    }
}

/* ---------------------------------------------------------
   16.2 — LINKEDIN CONNECT
   Redirects to LinkedIn OAuth
--------------------------------------------------------- */
function linkedInConnect() {
    window.location.href = "/linkedin/login";
}

/* ---------------------------------------------------------
   16.3 — LINKEDIN DISCONNECT
--------------------------------------------------------- */
async function linkedInDisconnect() {
    await fetch("/linkedin/logout");
    checkLinkedInStatus();
}

/* ---------------------------------------------------------
   16.4 — SEARCH CANDIDATES VIA BACKEND
   Calls Flask /linkedin/search endpoint.
   Returns real candidates when Talent Solutions approved,
   smart fake data until then.
--------------------------------------------------------- */
async function searchLinkedInCandidates(role, location, skills, booleanQuery) {
    try {
        const res = await fetch("/linkedin/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                role,
                location,
                skills,
                boolean_query: booleanQuery
            })
        });

        const data = await res.json();

        if (!data.ok) {
            console.error("LinkedIn search failed:", data.error);
            return null;
        }

        // Show demo banner if using fake data
        if (data.source === "demo") {
            showDemoBanner();
        } else {
            hideDemoBanner();
        }

        return data.candidates;

    } catch (err) {
        console.error("LinkedIn search error:", err);
        return null;
    }
}

/* ---------------------------------------------------------
   16.5 — DEMO MODE BANNER
--------------------------------------------------------- */
function showDemoBanner() {
    const existing = document.getElementById("demoBanner");
    if (existing) return;

    const banner = document.createElement("div");
    banner.id = "demoBanner";
    banner.className = "demo-mode-banner";
    banner.innerHTML = `
        ⚡ Demo mode — showing smart sample candidates.
        Real LinkedIn data available once Talent Solutions is approved.
    `;

    const resultsGrid = document.getElementById("resultsGrid");
    if (resultsGrid && resultsGrid.parentNode) {
        resultsGrid.parentNode.insertBefore(banner, resultsGrid);
    }
}

function hideDemoBanner() {
    const banner = document.getElementById("demoBanner");
    if (banner) banner.remove();
}

/* ---------------------------------------------------------
   16.6 — ADD LINKEDIN BADGE TO CANDIDATE CARDS
   Adds a small "via LinkedIn" badge to each result card
--------------------------------------------------------- */
function attachLinkedInBadges() {
    document.querySelectorAll(".result-card, .ctc").forEach(card => {
        if (card.querySelector(".linkedin-source-badge")) return;

        const header = card.querySelector(".result-header-text, .ctc-name");
        if (!header) return;

        const badge = document.createElement("span");
        badge.className = "linkedin-source-badge";
        badge.innerHTML = `in LinkedIn`;
        header.appendChild(badge);
    });
}

/* ---------------------------------------------------------
   16.7 — PHASE 16 MAIN RUNNER
   Replaces fake candidate search with backend call.
   Call this instead of using hardcoded fakeCandidates.
--------------------------------------------------------- */
async function runPhase16Search(role, location, skills, booleanQuery) {
    // Show searching indicator in AI stream
    pushAILine("Sourcing candidates from LinkedIn...", false, 400, false);

    const candidates = await searchLinkedInCandidates(role, location, skills, booleanQuery);

    if (!candidates || candidates.length === 0) {
        pushAILine("No candidates found. Try adjusting the role or skills.", true, 0, false);
        return [];
    }

    pushAILine(`Found ${candidates.length} matched candidates. Ranking by tier...`, false, 200, false);

    // Attach LinkedIn badges after cards render
    setTimeout(() => attachLinkedInBadges(), 500);

    return candidates;
}

/* ---------------------------------------------------------
   16.8 — INIT
   Run on page load
--------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
    checkLinkedInStatus();
});