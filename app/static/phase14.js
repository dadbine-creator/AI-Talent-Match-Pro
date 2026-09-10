/* ============================================================
   PHASE 14 — TOP-3 RANKING ENGINE + TIER CARD GENERATOR
   Scoring model · Weighting system · Explanation engine
   Vertical scroll cards · Gold / Silver / Bronze
   ============================================================ */

/* ---------------------------------------------------------
   14.1 — ELEMENT HOOKS
--------------------------------------------------------- */
const top3Panel = document.getElementById("top3Panel");
const top3Grid = document.getElementById("top3Grid");
const tierCardsContainer = document.getElementById("tierCardsContainer");

/* ---------------------------------------------------------
   14.2 — SCORING WEIGHTS
--------------------------------------------------------- */
const SCORING_WEIGHTS = {
    titleMatch:      0.30,
    skillMatch:      0.25,
    seniorityFit:    0.20,
    locationFit:     0.10,
    tenureFit:       0.10,
    trajectoryFit:   0.05
};

/* ---------------------------------------------------------
   14.3 — TITLE MATCH SCORER
--------------------------------------------------------- */
function scoreTitleMatch(candidateRole, targetRole) {
    if (!candidateRole || !targetRole) return 0;
    const c = candidateRole.toLowerCase();
    const t = targetRole.toLowerCase();
    if (c === t) return 100;
    const cWords = new Set(c.split(/\s+/));
    const tWords = new Set(t.split(/\s+/));
    const intersection = [...cWords].filter(w => tWords.has(w));
    const union = new Set([...cWords, ...tWords]);
    const jaccardScore = intersection.length / union.size;
    const seniorityBonus = ["senior", "lead", "head", "director", "vp"].some(k =>
        c.includes(k) && t.includes(k)
    ) ? 15 : 0;
    return Math.min(100, Math.round(jaccardScore * 100 + seniorityBonus));
}

/* ---------------------------------------------------------
   14.4 — SKILL MATCH SCORER
--------------------------------------------------------- */
function scoreSkillMatch(candidateSkills, requiredSkills) {
    if (!requiredSkills || !requiredSkills.trim()) return 75;
    if (!candidateSkills) return 0;
    const required = requiredSkills.toLowerCase().split(",").map(s => s.trim()).filter(Boolean);
    const candidate = Array.isArray(candidateSkills)
        ? candidateSkills.map(s => s.toLowerCase())
        : candidateSkills.toLowerCase().split(",").map(s => s.trim());
    if (!required.length) return 75;
    const matched = required.filter(req =>
        candidate.some(c => c.includes(req) || req.includes(c))
    );
    return Math.round((matched.length / required.length) * 100);
}

/* ---------------------------------------------------------
   14.5 — SENIORITY FIT SCORER
--------------------------------------------------------- */
function scoreSeniorityFit(candidateRole, targetRole) {
    const seniorityLevels = {
        "intern": 0, "junior": 1, "coordinator": 2, "associate": 2,
        "specialist": 3, "analyst": 3, "manager": 4, "senior": 5,
        "lead": 6, "head": 7, "director": 8, "vp": 9, "cmo": 10, "ceo": 10
    };
    const getLevel = (title) => {
        if (!title) return 4;
        const lower = title.toLowerCase();
        for (const [key, val] of Object.entries(seniorityLevels)) {
            if (lower.includes(key)) return val;
        }
        return 4;
    };
    const delta = Math.abs(getLevel(candidateRole) - getLevel(targetRole));
    if (delta === 0) return 100;
    if (delta === 1) return 80;
    if (delta === 2) return 55;
    if (delta === 3) return 30;
    return 10;
}

/* ---------------------------------------------------------
   14.6 — LOCATION FIT SCORER
--------------------------------------------------------- */
function scoreLocationFit(candidateLocation, targetLocation) {
    if (!targetLocation || !targetLocation.trim()) return 80;
    if (!candidateLocation) return 50;
    const c = candidateLocation.toLowerCase();
    const t = targetLocation.toLowerCase();
    if (c.includes(t) || t.includes(c)) return 100;
    if (c.includes("remote") || t.includes("remote")) return 85;
    const countries = ["us", "uk", "usa", "united states", "united kingdom", "germany", "france"];
    for (const country of countries) {
        if (c.includes(country) && t.includes(country)) return 70;
    }
    return 30;
}

/* ---------------------------------------------------------
   14.7 — TENURE FIT SCORER
--------------------------------------------------------- */
function scoreTenureFit(yearsExp) {
    if (!yearsExp) return 60;
    const match = String(yearsExp).match(/(\d+)/);
    if (!match) return 60;
    const years = parseInt(match[1]);
    if (years >= 5 && years <= 12) return 100;
    if (years >= 3 && years < 5)   return 80;
    if (years >= 12 && years <= 16) return 75;
    if (years >= 1 && years < 3)   return 55;
    return 40;
}

/* ---------------------------------------------------------
   14.8 — TRAJECTORY FIT SCORER
--------------------------------------------------------- */
function scoreTrajectoryFit(candidateRole) {
    if (!candidateRole) return 60;
    const lower = candidateRole.toLowerCase();
    const positive = ["growth", "strategy", "lead", "senior", "head", "director", "vp"];
    const negative = ["intern", "junior", "assistant", "coordinator"];
    const pos = positive.filter(s => lower.includes(s)).length;
    const neg = negative.filter(s => lower.includes(s)).length;
    if (pos >= 2) return 95;
    if (pos === 1 && neg === 0) return 80;
    if (pos === 0 && neg === 0) return 65;
    if (neg >= 1) return 40;
    return 60;
}

/* ---------------------------------------------------------
   14.9 — MASTER SCORING ENGINE
--------------------------------------------------------- */
function scoreCandidate(candidate, targetRole, targetSkills, targetLocation) {
    const titleScore      = scoreTitleMatch(candidate.role, targetRole);
    const skillScore      = scoreSkillMatch(candidate.skills, targetSkills);
    const seniorityScore  = scoreSeniorityFit(candidate.role, targetRole);
    const locationScore   = scoreLocationFit(candidate.location, targetLocation);
    const tenureScore     = scoreTenureFit(candidate.years);
    const trajectoryScore = scoreTrajectoryFit(candidate.role);

    const composite = Math.round(
        titleScore      * SCORING_WEIGHTS.titleMatch +
        skillScore      * SCORING_WEIGHTS.skillMatch +
        seniorityScore  * SCORING_WEIGHTS.seniorityFit +
        locationScore   * SCORING_WEIGHTS.locationFit +
        tenureScore     * SCORING_WEIGHTS.tenureFit +
        trajectoryScore * SCORING_WEIGHTS.trajectoryFit
    );

    return {
        composite,
        breakdown: { titleScore, skillScore, seniorityScore, locationScore, tenureScore, trajectoryScore }
    };
}

/* ---------------------------------------------------------
   14.10 — EXPLANATION ENGINE
--------------------------------------------------------- */
function generateRankExplanation(candidate, scores, rank) {
    const { breakdown, composite } = scores;
    const strengths = [];
    const gaps = [];

    if (breakdown.titleScore >= 80)      strengths.push("strong title alignment");
    else if (breakdown.titleScore < 50)  gaps.push("title mismatch");
    if (breakdown.skillScore >= 80)      strengths.push("high skill overlap");
    else if (breakdown.skillScore < 50)  gaps.push("skill gaps present");
    if (breakdown.seniorityScore >= 80)  strengths.push("ideal seniority level");
    else if (breakdown.seniorityScore < 50) gaps.push("seniority delta");
    if (breakdown.locationScore >= 80)   strengths.push("location match");
    else if (breakdown.locationScore < 50) gaps.push("location mismatch");
    if (breakdown.tenureScore >= 80)     strengths.push("stable tenure trajectory");

    const rankLabels = { 1: "top pick", 2: "strong runner-up", 3: "solid third choice" };
    let explanation = `Ranked #${rank} as your ${rankLabels[rank] || "ranked candidate"} with a composite score of ${composite}/100. `;
    if (strengths.length) explanation += `Key strengths: ${strengths.join(", ")}. `;
    if (gaps.length)      explanation += `Watch for: ${gaps.join(", ")}.`;
    return explanation.trim();
}

/* ---------------------------------------------------------
   14.11 — DELTA HIGHLIGHTER
--------------------------------------------------------- */
function computeDeltas(ranked) {
    if (ranked.length < 2) return ranked;
    const topScore = ranked[0].scores.composite;
    return ranked.map((c, i) => ({
        ...c,
        delta: i === 0 ? null : topScore - c.scores.composite
    }));
}

/* ---------------------------------------------------------
   14.12 — TOP-3 RANKER
--------------------------------------------------------- */
function rankTop3(candidates, targetRole, targetSkills, targetLocation) {
    if (!candidates || candidates.length === 0) return [];
    const scored = candidates.map(candidate => ({
        ...candidate,
        scores: scoreCandidate(candidate, targetRole, targetSkills, targetLocation)
    }));
    scored.sort((a, b) => b.scores.composite - a.scores.composite);
    const top3 = scored.slice(0, 3);
    const ranked = top3.map((candidate, i) => ({
        ...candidate,
        rank: i + 1,
        rankExplanation: generateRankExplanation(candidate, candidate.scores, i + 1)
    }));
    return computeDeltas(ranked);
}

/* ---------------------------------------------------------
   14.13 — TIER CONFIG
   Gold = 100%, Silver = 90%, Bronze = 80%
   Only shows qualities the candidate HAS — no negatives.
--------------------------------------------------------- */
const TIER_CONFIG = {
    gold: {
        label: "Gold Tier",
        pctClass: "ctc-pct-gold",
        borderClass: "ctc-gold",
        trophy: "🏆",
        qualities: [
            "Title perfectly matches the role",
            "All core skills align with requirements",
            "Seniority level is exactly aligned",
            "Experience fully meets expectations",
            "Boolean relevance is complete",
            "Career trajectory fits the role perfectly",
            "Location match confirmed",
            "Tenure stability score is excellent",
            "Industry background is highly relevant"
        ]
    },
    silver: {
        label: "Silver Tier",
        pctClass: "ctc-pct-silver",
        borderClass: "ctc-silver",
        trophy: "🥈",
        qualities: [
            "Title closely matches the role",
            "Most core skills align with requirements",
            "Seniority level is a strong fit",
            "Experience largely meets expectations",
            "Boolean relevance is strong",
            "Career trajectory is well aligned",
            "Location is within target range",
            "Tenure shows good stability"
        ]
    },
    bronze: {
        label: "Bronze Tier",
        pctClass: "ctc-pct-bronze",
        borderClass: "ctc-bronze",
        trophy: "🥉",
        qualities: [
            "Title has meaningful overlap with the role",
            "Key skills are present",
            "Seniority is reasonably aligned",
            "Experience partially meets expectations",
            "Boolean relevance is solid",
            "Career trajectory shows promise"
        ]
    }
};

const MAX_VISIBLE_QUALITIES = 6;

/* ---------------------------------------------------------
   14.14 — GET TIER KEY
--------------------------------------------------------- */
function getTierKey(candidate) {
    const score = candidate.score || 0;
    const tier  = String(candidate.tier || "").toLowerCase();
    if (tier === "gold"   || tier === "100" || score >= 95) return "gold";
    if (tier === "silver" || tier === "90"  || score >= 85) return "silver";
    return "bronze";
}

/* ---------------------------------------------------------
   14.15 — CREATE TIER CARD
   candidate = { name, role, photo, linkedin, tier, score }
   Returns a DOM element ready to append.
--------------------------------------------------------- */
function createTierCard(candidate) {
    const tierKey = getTierKey(candidate);
    const config  = TIER_CONFIG[tierKey];
    const pct     = candidate.score
        ? Math.round(candidate.score) + "%"
        : tierKey === "gold" ? "100%" : tierKey === "silver" ? "90%" : "80%";

    const photoSrc = candidate.photo || "/static/profile_placeholder.png";
    const hasMore  = config.qualities.length > MAX_VISIBLE_QUALITIES;

    const card = document.createElement("div");
    card.className = `ctc ${config.borderClass}`;

    const qualitiesHtml = config.qualities.map((q, i) => `
        <div class="ctc-q${i >= MAX_VISIBLE_QUALITIES ? " hidden" : ""}">
            <span class="ctc-check">✓</span>
            <span>${q}</span>
        </div>
    `).join("");

    card.innerHTML = `
        <div class="ctc-photo-wrap">
            <img class="ctc-photo"
                 src="${photoSrc}"
                 alt="${candidate.name || "Candidate"}"
                 onerror="this.src='/static/profile_placeholder.png'" />
            <span class="ctc-trophy">${config.trophy}</span>
        </div>

        <div class="ctc-tier-row">
            <div class="ctc-tier-line"></div>
            <span class="ctc-tier-text">
                ${config.label} | <span class="${config.pctClass}">${pct}</span>
            </span>
            <div class="ctc-tier-line"></div>
        </div>

        <div class="ctc-name">${candidate.name || "Candidate"}</div>
        <div class="ctc-role">${candidate.role || ""}</div>

        <div class="ctc-divider"></div>

        <div class="ctc-qualities">
            ${qualitiesHtml}
        </div>

        <div class="ctc-divider"></div>

        ${hasMore ? `<button class="ctc-read-more">Read more</button>` : ""}
        ${candidate.linkedin
            ? `<a class="ctc-linkedin" href="${candidate.linkedin}" target="_blank" rel="noopener">View LinkedIn →</a>`
            : ""}
    `;

    // Read more toggle
    if (hasMore) {
        const btn = card.querySelector(".ctc-read-more");
        let expanded = false;
        btn.addEventListener("click", () => {
            expanded = !expanded;
            card.querySelectorAll(".ctc-q").forEach((row, i) => {
                if (i >= MAX_VISIBLE_QUALITIES) row.classList.toggle("hidden", !expanded);
            });
            btn.textContent = expanded ? "Show less" : "Read more";
        });
    }

    return card;
}

/* ---------------------------------------------------------
   14.16 — RENDER TIER CARDS
   Renders all candidates as vertical stacked tier cards.
   Call this after search results come back.

   Usage in runSearch():
     renderTierCards(fakeCandidates, "tierCardsContainer");
--------------------------------------------------------- */
function renderTierCards(candidates, containerId = "tierCardsContainer") {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = "";
    container.className = "tier-cards-scroll";

    candidates.forEach((candidate, i) => {
        const card = createTierCard(candidate);
        card.classList.add("kinetic-settle");
        card.style.animationDelay = `${i * 0.12}s`;
        container.appendChild(card);
    });
}

/* ---------------------------------------------------------
   14.17 — INTEGRATION HOOK
   Call this after renderProDashboard() in runSearch().
--------------------------------------------------------- */
function runPhase14(candidates) {
    const targetRole     = positionTitleInput ? positionTitleInput.value.trim() : "";
    const targetSkills   = skillsInput ? skillsInput.value.trim() : "";
    const targetLocation = locationInput ? locationInput.value.trim() : "";

    // Render vertical tier cards
    renderTierCards(candidates, "tierCardsContainer");

    // Also run the scoring engine for top-3 analytics panel
    if (top3Panel && top3Grid) {
        const ranked = rankTop3(candidates, targetRole, targetSkills, targetLocation);
        if (!ranked.length) { top3Panel.style.display = "none"; return; }

        top3Panel.style.display = "block";
        top3Grid.innerHTML = "";

        ranked.forEach((candidate, i) => {
            const card = document.createElement("div");
            card.className = `top3-card top3-rank-${candidate.rank}`;
            const rankLabels = { 1: "🥇 #1 Top Pick", 2: "🥈 #2 Runner-Up", 3: "🥉 #3 Strong Fit" };
            const deltaHtml = candidate.delta !== null
                ? `<div class="top3-delta">−${candidate.delta} pts vs #1</div>`
                : `<div class="top3-delta top3-delta-leader">Leader</div>`;

            const breakdownHtml = Object.entries(candidate.scores.breakdown).map(([key, val]) => {
                const labels = {
                    titleScore: "Title", skillScore: "Skills",
                    seniorityScore: "Seniority", locationScore: "Location",
                    tenureScore: "Tenure", trajectoryScore: "Trajectory"
                };
                return `
                    <div class="top3-breakdown-row">
                        <span class="top3-breakdown-label">${labels[key] || key}</span>
                        <div class="top3-breakdown-bar">
                            <div class="top3-breakdown-fill" style="width:${Math.max(val, 3)}%"></div>
                        </div>
                        <span class="top3-breakdown-val">${val}</span>
                    </div>
                `;
            }).join("");

            card.innerHTML = `
                <div class="top3-card-header">
                    <div class="top3-rank-badge">${rankLabels[candidate.rank]}</div>
                    ${deltaHtml}
                </div>
                <div class="top3-candidate-name">${candidate.name || "Candidate"}</div>
                <div class="top3-candidate-role">${candidate.role || ""}</div>
                <div class="top3-candidate-meta">
                    <span>${candidate.location || ""}</span>
                    <span>${candidate.years || ""}</span>
                </div>
                <div class="top3-composite-row">
                    <div class="top3-composite-score">${candidate.scores.composite}</div>
                    <div class="top3-composite-label">/ 100 composite</div>
                </div>
                <div class="top3-breakdown">${breakdownHtml}</div>
                <div class="top3-explanation">${candidate.rankExplanation}</div>
                ${candidate.linkedin
                    ? `<a class="top3-linkedin-btn" href="${candidate.linkedin}" target="_blank" rel="noopener">View LinkedIn →</a>`
                    : ""}
            `;

            card.style.animationDelay = `${i * 0.12}s`;
            card.classList.add("top3-card-enter");
            top3Grid.appendChild(card);
        });
    }
}