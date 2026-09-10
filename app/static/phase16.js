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
   REMOVED — LinkedIn candidate sourcing
   searchLinkedInCandidates() / runPhase16Search() / the demo banner
   / attachLinkedInBadges() all called POST /linkedin/search, which is
   not a route on this server. The whole path 404'd, so the
   "Sourcing candidates from LinkedIn…" status line was shown for
   something that could never run.
   Removed rather than relabelled: we don't show an entry point for a
   feature that doesn't exist.
   The OAuth sign-in above (checkLinkedInStatus / linkedInConnect /
   linkedInDisconnect) is real and stays.
--------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
    checkLinkedInStatus();
});