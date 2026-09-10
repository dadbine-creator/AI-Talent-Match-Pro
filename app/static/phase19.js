/* ============================================================
   PHASE 19 — THEME SYSTEM + SHORTLIST + NOTES
   Auto detect · Light/Dark toggle · Persistence
   Shortlist engine · Notes engine
   ============================================================ */

/* ---------------------------------------------------------
   19.1 — THEME SYSTEM
--------------------------------------------------------- */
const THEME_KEY = "atmpro_theme";

// Detect system preference
function getSystemTheme() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// Get saved theme or fall back to system preference
function getSavedTheme() {
    return localStorage.getItem(THEME_KEY) || getSystemTheme();
}

// Apply theme to document
function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    updateToggleButton(theme);
}

// Save theme preference
function saveTheme(theme) {
    try {
        localStorage.setItem(THEME_KEY, theme);
    } catch (err) {
        console.warn("Theme could not be saved:", err);
    }
}

// Toggle between light and dark
function toggleTheme() {
    const current = document.documentElement.dataset.theme || "dark";
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    saveTheme(next);
}

// Update toggle button icon
function updateToggleButton(theme) {
    const btn = document.getElementById("p19ThemeToggle");
    if (!btn) return;
    btn.textContent = theme === "dark" ? "☀️" : "🌙";
    btn.title = theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode";
}

// Listen for system theme changes
function watchSystemTheme() {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
        // Only auto-switch if user hasn't manually set a preference
        const saved = localStorage.getItem(THEME_KEY);
        if (!saved) {
            applyTheme(e.matches ? "dark" : "light");
        }
    });
}

// Init theme on load
function initTheme() {
    const theme = getSavedTheme();
    applyTheme(theme);
    watchSystemTheme();
}

/* ---------------------------------------------------------
   19.2 — INJECT THEME TOGGLE BUTTON INTO TOPBAR
--------------------------------------------------------- */
function injectThemeToggle() {
    const topbarRight = document.querySelector(".topbar-right");
    if (!topbarRight || document.getElementById("p19ThemeToggle")) return;

    const btn = document.createElement("button");
    btn.id = "p19ThemeToggle";
    btn.className = "p19-theme-toggle";
    btn.setAttribute("aria-label", "Toggle theme");
    btn.addEventListener("click", toggleTheme);

    topbarRight.insertBefore(btn, topbarRight.firstChild);
    updateToggleButton(document.documentElement.dataset.theme || "dark");
}

/* ---------------------------------------------------------
   19.3 — SHORTLIST ENGINE
--------------------------------------------------------- */
const SHORTLIST_KEY = "atmpro_shortlist";

function loadShortlist() {
    try {
        return JSON.parse(localStorage.getItem(SHORTLIST_KEY) || "[]");
    } catch { return []; }
}

function saveShortlist(list) {
    try {
        localStorage.setItem(SHORTLIST_KEY, JSON.stringify(list));
    } catch (err) {
        console.warn("Shortlist could not be saved:", err);
    }
}

function isShortlisted(candidateName, role) {
    const list = loadShortlist();
    return list.some(c => c.name === candidateName && c.role === role);
}

function addToShortlist(candidate) {
    const list = loadShortlist();
    const exists = list.some(c => c.name === candidate.name && c.role === candidate.role);
    if (!exists) {
        list.push({
            ...candidate,
            savedAt: Date.now(),
            note: ""
        });
        saveShortlist(list);
    }
}

function removeFromShortlist(candidateName, role) {
    const list = loadShortlist().filter(c => !(c.name === candidateName && c.role === role));
    saveShortlist(list);
}

function toggleShortlist(candidate) {
    if (isShortlisted(candidate.name, candidate.role)) {
        removeFromShortlist(candidate.name, candidate.role);
        return false;
    } else {
        addToShortlist(candidate);
        return true;
    }
}

/* ---------------------------------------------------------
   19.4 — NOTES ENGINE
--------------------------------------------------------- */
const NOTES_KEY = "atmpro_notes";

function loadNotes() {
    try {
        return JSON.parse(localStorage.getItem(NOTES_KEY) || "{}");
    } catch { return {}; }
}

function saveNote(candidateName, role, note) {
    try {
        const notes = loadNotes();
        const key = `${candidateName}_${role}`.toLowerCase().replace(/[^a-z0-9_]/g, "_");
        notes[key] = note;
        localStorage.setItem(NOTES_KEY, JSON.stringify(notes));

        // Also update shortlist note
        const list = loadShortlist();
        const idx = list.findIndex(c => c.name === candidateName && c.role === role);
        if (idx !== -1) {
            list[idx].note = note;
            saveShortlist(list);
        }
    } catch (err) {
        console.warn("Note could not be saved:", err);
    }
}

function getNote(candidateName, role) {
    const notes = loadNotes();
    const key = `${candidateName}_${role}`.toLowerCase().replace(/[^a-z0-9_]/g, "_");
    return notes[key] || "";
}

/* ---------------------------------------------------------
   19.5 — ATTACH SHORTLIST BUTTON TO TIER CARDS
--------------------------------------------------------- */
function attachShortlistButtons(candidates) {
    setTimeout(() => {
        const cards = document.querySelectorAll(".p17-tier-card");
        cards.forEach((card, index) => {
            if (card.querySelector(".p19-shortlist-btn")) return;

            const candidate = candidates[index];
            if (!candidate) return;

            card.style.position = "relative";

            const btn = document.createElement("button");
            btn.className = "p19-shortlist-btn";
            const saved = isShortlisted(candidate.name, candidate.role || "");
            btn.textContent = saved ? "🔖" : "🔖";
            btn.style.opacity = saved ? "1" : "0.4";
            btn.setAttribute("aria-label", saved ? "Remove from shortlist" : "Add to shortlist");
            btn.title = saved ? "Remove from shortlist" : "Save to shortlist";

            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const isSaved = toggleShortlist(candidate);
                btn.style.opacity = isSaved ? "1" : "0.4";
                btn.setAttribute("aria-label", isSaved ? "Remove from shortlist" : "Add to shortlist");
                btn.title = isSaved ? "Remove from shortlist" : "Save to shortlist";

                // Show toast
                showToast(isSaved ? "Saved to Shortlist ✓" : "Removed from Shortlist");
            });

            card.appendChild(btn);
        });
    }, 500);
}

/* ---------------------------------------------------------
   19.6 — TOAST NOTIFICATION
--------------------------------------------------------- */
function showToast(message) {
    const existing = document.getElementById("p19Toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
    toast.id = "p19Toast";
    toast.style.cssText = `
        position: fixed;
        bottom: 24px;
        left: 50%;
        transform: translateX(-50%);
        background: var(--p19-cyan, #00B7C7);
        color: #fff;
        padding: 10px 20px;
        border-radius: 999px;
        font-size: 13px;
        font-weight: 600;
        z-index: 9999;
        animation: p18FadeIn 0.3s ease both;
        box-shadow: 0 4px 20px rgba(0,183,199,0.4);
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2500);
}

/* ---------------------------------------------------------
   19.7 — RENDER SHORTLIST VIEW
   Shows when HR clicks "Shortlists" in sidebar
--------------------------------------------------------- */
function renderShortlistView() {
    const centerEmpty = document.getElementById("centerEmpty");
    const formCard = document.getElementById("formCard");
    const proDashboard = document.getElementById("proDashboard");

    if (centerEmpty) centerEmpty.style.display = "none";
    if (formCard) formCard.style.display = "none";
    if (proDashboard) proDashboard.style.display = "none";

    // Remove existing shortlist view
    const existing = document.getElementById("p19ShortlistView");
    if (existing) existing.remove();

    const list = loadShortlist();
    const centerPanel = document.querySelector(".center-panel");
    if (!centerPanel) return;

    const view = document.createElement("div");
    view.id = "p19ShortlistView";
    view.className = "p19-shortlist-view";

    // Header
    const header = document.createElement("div");
    header.className = "p19-shortlist-header";
    header.innerHTML = `
        <div class="p19-shortlist-title">🔖 Shortlists</div>
        <div class="p19-shortlist-count">${list.length} candidate${list.length !== 1 ? "s" : ""} saved</div>
    `;
    view.appendChild(header);

    if (list.length === 0) {
        const empty = document.createElement("div");
        empty.className = "p19-shortlist-empty";
        empty.innerHTML = `
            <span class="p19-shortlist-empty-icon">🔖</span>
            No candidates shortlisted yet.<br>
            Click the bookmark icon on any candidate card to save them here.
        `;
        view.appendChild(empty);
    } else {
        list.forEach(candidate => {
            const tierKey = candidate.tier === "100" || candidate.tier === "gold" ? "gold"
                          : candidate.tier === "90" || candidate.tier === "silver" ? "silver"
                          : "bronze";

            const tierLabel = tierKey === "gold" ? "Gold Tier" : tierKey === "silver" ? "Silver Tier" : "Bronze Tier";
            const linkedinUrl = candidate.linkedin || candidate.linkedin_url || "#";
            const note = getNote(candidate.name, candidate.role || "");

            const card = document.createElement("div");
            card.className = "p19-shortlist-card";
            card.innerHTML = `
                <div class="p19-shortlist-photo">👤</div>
                <div class="p19-shortlist-info">
                    <div class="p19-shortlist-name">${candidate.name || "Candidate"}</div>
                    <div class="p19-shortlist-role">${candidate.role || ""}</div>
                    <span class="p19-shortlist-tier ${tierKey}">${tierLabel}</span>
                    <textarea class="p19-note-input" placeholder="Add a note..." rows="2">${note}</textarea>
                </div>
                <div class="p19-shortlist-actions">
                    <button class="p19-remove-btn" title="Remove from shortlist">✕</button>
                    <a class="p19-linkedin-btn" href="${linkedinUrl}" target="_blank" rel="noopener noreferrer">
                        <span style="font-weight:800;font-style:italic;">in</span>
                        LinkedIn
                    </a>
                </div>
            `;

            // Note auto-save with debounce
            const noteInput = card.querySelector(".p19-note-input");
            let noteTimer;
            noteInput.addEventListener("input", () => {
                clearTimeout(noteTimer);
                noteTimer = setTimeout(() => {
                    saveNote(candidate.name, candidate.role || "", noteInput.value);
                }, 350);
            });

            // Remove button
            const removeBtn = card.querySelector(".p19-remove-btn");
            removeBtn.addEventListener("click", () => {
                removeFromShortlist(candidate.name, candidate.role || "");
                card.style.animation = "p18ScaleOut 0.2s ease both";
                setTimeout(() => renderShortlistView(), 250);
                showToast("Removed from Shortlist");
            });

            view.appendChild(card);
        });
    }

    // Insert safely — guard for missing topbar
    const topbar = centerPanel.querySelector(".topbar");
    if (topbar) {
        centerPanel.insertBefore(view, topbar.nextSibling);
    } else {
        centerPanel.prepend(view);
    }
}

/* ---------------------------------------------------------
   19.8 — WIRE SHORTLISTS SIDEBAR ITEM
--------------------------------------------------------- */
function wireShortlistsSidebarItem() {
    const sidebarItems = document.querySelectorAll(".sidebar-item");
    sidebarItems.forEach(item => {
        const label = item.querySelector(".sidebar-label");
        if (label && label.textContent.trim() === "Shortlists") {
            item.style.cursor = "pointer";
            item.addEventListener("click", () => {
                // Remove active from all
                sidebarItems.forEach(i => i.classList.remove("active"));
                item.classList.add("active");
                renderShortlistView();
            });
        }

        // Your Roles — restore workspace
        if (label && label.textContent.trim() === "Your Roles") {
            item.addEventListener("click", () => {
                const shortlistView = document.getElementById("p19ShortlistView");
                if (shortlistView) shortlistView.remove();
            });
        }
    });
}

/* ---------------------------------------------------------
   19.9 — PHASE 19 MASTER RUNNER
--------------------------------------------------------- */
function runPhase19(candidates) {
    if (candidates && candidates.length > 0) {
        attachShortlistButtons(candidates);
    }
}

/* ---------------------------------------------------------
   19.10 — INIT ON PAGE LOAD
--------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    injectThemeToggle();
    wireShortlistsSidebarItem();
});