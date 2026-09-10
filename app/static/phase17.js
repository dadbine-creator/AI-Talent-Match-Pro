/* ============================================================
   PHASE 17 — PREMIUM CANDIDATE CARDS + ADAPTIVE SCORING
   All improvements applied:
   - Better key normalization
   - localStorage error handling
   - Data attribute checklist toggle
   - Accessibility aria-labels
   - DocumentFragment batch rendering
   - Feedback indicator on card
   ============================================================ */

/* ---------------------------------------------------------
   17.1 — FEEDBACK STORAGE
--------------------------------------------------------- */
const FEEDBACK_KEY = "atmpro_feedback";

function loadFeedback() {
    try {
        const raw = localStorage.getItem(FEEDBACK_KEY);
        return raw ? JSON.parse(raw) : {};
    } catch { return {}; }
}

function saveFeedback(data) {
    // Improvement 2 — wrap in try/catch for quota/privacy errors
    try {
        localStorage.setItem(FEEDBACK_KEY, JSON.stringify(data));
    } catch (err) {
        console.warn("Feedback could not be saved:", err);
    }
}

function recordFeedback(candidateName, role, sentiment) {
    const feedback = loadFeedback();
    // Improvement 1 — strip special characters to avoid key collisions
    const key = `${candidateName}_${role}`.toLowerCase().replace(/[^a-z0-9_]/g, "_");
    feedback[key] = {
        name: candidateName,
        role: role,
        sentiment: sentiment,
        timestamp: Date.now()
    };
    saveFeedback(feedback);
    showLearningBadge();
}

function getFeedbackForCandidate(candidateName, role) {
    const feedback = loadFeedback();
    // Improvement 1 — same normalization
    const key = `${candidateName}_${role}`.toLowerCase().replace(/[^a-z0-9_]/g, "_");
    return feedback[key]?.sentiment || null;
}

/* ---------------------------------------------------------
   17.2 — ADAPTIVE SCORE RECALIBRATION
--------------------------------------------------------- */
function recalibrateScore(candidate, baseScore) {
    const feedback = loadFeedback();
    const entries = Object.values(feedback);

    if (entries.length === 0) return baseScore;

    const similarPositive = entries.filter(f =>
        f.sentiment === "up" &&
        f.role && candidate.role &&
        f.role.toLowerCase().split(" ").some(word =>
            candidate.role.toLowerCase().includes(word) && word.length > 3
        )
    ).length;

    const similarNegative = entries.filter(f =>
        f.sentiment === "down" &&
        f.role && candidate.role &&
        f.role.toLowerCase().split(" ").some(word =>
            candidate.role.toLowerCase().includes(word) && word.length > 3
        )
    ).length;

    let adjustment = (similarPositive * 2) - (similarNegative * 3);
    adjustment = Math.max(-15, Math.min(10, adjustment));

    return Math.max(0, Math.min(100, baseScore + adjustment));
}

/* ---------------------------------------------------------
   17.3 — LEARNING BADGE
--------------------------------------------------------- */
function showLearningBadge() {
    const existing = document.getElementById("p17LearningBadge");
    if (existing) return;

    const container = document.getElementById("tierCardsContainer");
    if (!container) return;

    const badge = document.createElement("div");
    badge.id = "p17LearningBadge";
    badge.className = "p17-learning-badge";
    badge.innerHTML = `
        <div class="p17-learning-dot"></div>
        <span>AI is learning your preferences</span>
    `;

    container.insertBefore(badge, container.firstChild);
    setTimeout(() => badge.remove(), 4000);
}

/* ---------------------------------------------------------
   17.4 — QUALITY CHECKLIST GENERATOR
--------------------------------------------------------- */
function generateChecklist(tier, candidate) {
    const goldChecklist = [
        "Title perfectly matches the role",
        "All core skills align with requirements",
        "Seniority level is exactly aligned",
        "Experience fully meets expectations",
        "Boolean relevance is complete",
        "Career trajectory fits the role perfectly",
        "Location match confirmed",
        "Tenure stability is excellent",
        "Industry background is highly relevant"
    ];

    const silverChecklist = [
        "Title closely matches the role",
        "Most core skills align",
        "Seniority is a strong fit",
        "Experience largely meets expectations",
        "Boolean relevance is strong",
        "Career trajectory is well aligned",
        "Location within target range",
        "Tenure shows good stability"
    ];

    const bronzeChecklist = [
        "Title has meaningful overlap",
        "Key skills are present",
        "Seniority is reasonably aligned",
        "Experience partially meets expectations",
        "Boolean relevance is solid",
        "Career trajectory shows promise"
    ];

    if (tier === "gold" || tier === "100") return goldChecklist;
    if (tier === "silver" || tier === "90") return silverChecklist;
    return bronzeChecklist;
}

/* ---------------------------------------------------------
   17.5 — TIER CARD BUILDER
--------------------------------------------------------- */
function buildP17TierCard(candidate, tierKey) {
    const tierMap = {
        "100":    { label: "Gold Tier",   pctClass: "gold-pct",   cardClass: "gold-card",   trophy: "🏆" },
        "90":     { label: "Silver Tier", pctClass: "silver-pct", cardClass: "silver-card", trophy: "🥈" },
        "80":     { label: "Bronze Tier", pctClass: "bronze-pct", cardClass: "bronze-card", trophy: "🥉" },
        "gold":   { label: "Gold Tier",   pctClass: "gold-pct",   cardClass: "gold-card",   trophy: "🏆" },
        "silver": { label: "Silver Tier", pctClass: "silver-pct", cardClass: "silver-card", trophy: "🥈" },
        "bronze": { label: "Bronze Tier", pctClass: "bronze-pct", cardClass: "bronze-card", trophy: "🥉" },
    };

    const t = tierMap[tierKey] || tierMap["80"];
    const checklist = generateChecklist(tierKey, candidate);
    const baseScore = candidate.score || (tierKey === "100" || tierKey === "gold" ? 94 : tierKey === "90" || tierKey === "silver" ? 89 : 83);
    const adjustedScore = recalibrateScore(candidate, baseScore);
    const existingFeedback = getFeedbackForCandidate(candidate.name, candidate.role);

    const photoUrl = candidate.photo || "";
    const photoContent = photoUrl
        ? `<img class="p17-photo" src="${photoUrl}" alt="${candidate.name}" />`
        : `<div class="p17-photo p17-photo-placeholder">👤</div>`;

    const card = document.createElement("div");
    card.className = `p17-tier-card ${t.cardClass}`;

    // Improvement 3 — data attribute checklist toggle
    const checklistHTML = checklist.map((item, i) => {
        const isExtra = i >= 6;
        return `
            <div class="p17-check-row${isExtra ? " hidden" : ""}" data-extra="${isExtra}">
                <span class="p17-check-icon" aria-hidden="true">✓</span>
                <span>${item}</span>
            </div>
        `;
    }).join("");

    card.innerHTML = `
        <div class="p17-photo-wrap">
            ${photoContent}
            <span class="p17-trophy" aria-hidden="true">${t.trophy}</span>
        </div>

        <div class="p17-tier-row">
            <div class="p17-tier-line"></div>
            <span class="p17-tier-label">
                <span class="${t.pctClass}-name">${t.label}</span> | <span class="${t.pctClass}">${adjustedScore}%</span>
            </span>
            <div class="p17-tier-line"></div>
        </div>

        <div class="p17-name">${candidate.name || "Candidate"}</div>
        <div class="p17-role">${candidate.role || ""}</div>

        <div class="p17-divider"></div>

        <div class="p17-checklist" role="list">
            ${checklistHTML}
        </div>

        <div class="p17-divider"></div>

        <button class="p17-read-more" data-expanded="0" aria-label="Read more about ${candidate.name}">Read more</button>

        <div class="p17-divider"></div>

        <a class="p17-linkedin-link"
           href="${candidate.linkedin || candidate.linkedin_url || '#'}"
           target="_blank"
           rel="noopener noreferrer"
           aria-label="View ${candidate.name}'s LinkedIn profile">
            <span class="p17-linkedin-icon" aria-hidden="true">in</span>
            <span><strong>View LinkedIn</strong> Profile</span>
        </a>
    `;

    // Improvement 3 — data attribute toggle logic
    const readMoreBtn = card.querySelector(".p17-read-more");
    readMoreBtn.addEventListener("click", () => {
        const expanded = readMoreBtn.dataset.expanded !== "1";
        readMoreBtn.dataset.expanded = expanded ? "1" : "0";
        readMoreBtn.setAttribute("aria-expanded", expanded);
        card.querySelectorAll(".p17-check-row").forEach(row => {
            row.classList.toggle("hidden", !expanded && row.dataset.extra === "true");
        });
        readMoreBtn.textContent = expanded ? "Show less" : "Read more";
    });

    // Optional enhancement — feedback indicator on card
    if (existingFeedback) {
        const icon = document.createElement("span");
        icon.className = `p17-feedback-icon ${existingFeedback === "up" ? "thumb-up" : "thumb-down"}`;
        icon.textContent = existingFeedback === "up" ? "👍" : "👎";
        icon.title = existingFeedback === "up" ? "You liked this candidate" : "You passed on this candidate";
        const tierRow = card.querySelector(".p17-tier-row");
        if (tierRow) tierRow.appendChild(icon);
    }

    return card;
}

/* ---------------------------------------------------------
   17.6 — RENDER PHASE 17 TIER CARDS
   Improvement 6 — DocumentFragment batch rendering
--------------------------------------------------------- */
function renderP17TierCards(candidates) {
    const container = document.getElementById("tierCardsContainer");
    if (!container) return;

    container.innerHTML = "";

    if (!candidates || candidates.length === 0) return;

    // Improvement 6 — batch DOM insertions using fragment
    const fragment = document.createDocumentFragment();

    candidates.forEach((candidate, index) => {
        let tierKey = "bronze";

        if (candidate.tier === "100" || candidate.tier === "gold" || candidate.tierLabel?.toLowerCase().includes("gold")) {
            tierKey = "gold";
        } else if (candidate.tier === "90" || candidate.tier === "silver" || candidate.tierLabel?.toLowerCase().includes("silver")) {
            tierKey = "silver";
        } else if (candidate.tier === "80" || candidate.tier === "bronze" || candidate.tierLabel?.toLowerCase().includes("bronze")) {
            tierKey = "bronze";
        }

        const card = buildP17TierCard(candidate, tierKey);

        card.style.opacity = "0";
        card.style.transform = "translateY(16px)";
        card.style.transition = "opacity 0.4s ease, transform 0.4s ease";

        fragment.appendChild(card);

        setTimeout(() => {
            card.style.opacity = "1";
            card.style.transform = "translateY(0)";
        }, index * 150);
    });

    container.appendChild(fragment);
}

/* ---------------------------------------------------------
   17.7 — PHASE 17 MASTER RUNNER
--------------------------------------------------------- */
function runPhase17(candidates) {
    if (!candidates || candidates.length === 0) return;
    renderP17TierCards(candidates);
}