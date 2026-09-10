/* ============================================================
   PHASE 15 — AI PERSONA MATCHING ENGINE
   Clusters candidates into personas · Shows persona fit
   Persona cards · Match explanation · Radar breakdown
   ============================================================ */

/* ---------------------------------------------------------
   15.1 — PERSONA DEFINITIONS
   Each persona has a name, description, icon, key traits,
   and weighted skill signals used for matching.
--------------------------------------------------------- */
const PERSONA_DEFINITIONS = [
    {
        id: "strategist",
        name: "The Strategist",
        tagline: "Long-term vision, cross-functional leadership",
        icon: "♟",
        color: "persona-purple",
        traits: ["strategic thinking", "roadmap", "vision", "leadership", "planning", "stakeholders", "OKRs"],
        roleSignals: ["strategy", "director", "vp", "head of", "chief", "lead"],
        skillSignals: ["strategy", "planning", "roadmap", "leadership", "stakeholder", "executive"],
        description: "Operates at the intersection of business and product. Drives long-term direction, aligns teams, and owns outcomes at scale."
    },
    {
        id: "builder",
        name: "The Builder",
        tagline: "Hands-on executor, fast-paced environments",
        icon: "⚙",
        color: "persona-teal",
        traits: ["execution", "hands-on", "delivery", "build", "launch", "ship", "fast-paced"],
        roleSignals: ["manager", "lead", "senior", "specialist", "engineer", "developer"],
        skillSignals: ["execution", "delivery", "agile", "scrum", "launch", "build", "ship"],
        description: "Gets things done. Thrives in fast-moving environments where shipping and iteration matter more than process."
    },
    {
        id: "operator",
        name: "The Operator",
        tagline: "Process-driven, systems thinker, efficiency",
        icon: "◎",
        color: "persona-blue",
        traits: ["operations", "process", "systems", "efficiency", "scale", "workflows", "optimization"],
        roleSignals: ["operations", "ops", "coordinator", "analyst", "program", "project"],
        skillSignals: ["operations", "process", "systems", "efficiency", "automation", "workflows", "data"],
        description: "Designs and runs the systems that make organizations scale. Finds inefficiency and eliminates it."
    },
    {
        id: "innovator",
        name: "The Innovator",
        tagline: "Creative problem-solver, first-principles thinker",
        icon: "◈",
        color: "persona-amber",
        traits: ["innovation", "creative", "research", "experiment", "prototype", "design thinking", "novel"],
        roleSignals: ["innovation", "research", "design", "product", "ux", "creative", "experience"],
        skillSignals: ["innovation", "design thinking", "research", "prototyping", "experimentation", "creative"],
        description: "Challenges assumptions, invents new approaches, and turns ambiguous problems into elegant solutions."
    },
    {
        id: "growth",
        name: "The Growth Architect",
        tagline: "Data-driven, funnel-obsessed, CAC/LTV focus",
        icon: "▲",
        color: "persona-green",
        traits: ["growth", "acquisition", "funnel", "conversion", "CAC", "LTV", "retention", "paid", "SEO"],
        roleSignals: ["growth", "marketing", "acquisition", "demand", "performance", "revenue"],
        skillSignals: ["growth", "acquisition", "funnel", "conversion", "paid media", "seo", "analytics", "retention"],
        description: "Obsessed with the numbers behind growth. Owns the full funnel from awareness to retention and revenue."
    },
    {
        id: "lifecycle",
        name: "The Lifecycle Specialist",
        tagline: "Retention, CRM, segmentation, loyalty",
        icon: "↻",
        color: "persona-coral",
        traits: ["lifecycle", "retention", "CRM", "segmentation", "email", "loyalty", "churn", "engagement"],
        roleSignals: ["lifecycle", "crm", "retention", "engagement", "email", "customer success"],
        skillSignals: ["lifecycle", "crm", "retention", "segmentation", "email", "churn", "engagement", "loyalty"],
        description: "Keeps users coming back. Masters the art of engagement, segmentation, and turning one-time users into advocates."
    }
];

/* ---------------------------------------------------------
   15.2 — PERSONA MATCHER
   Scores a candidate against each persona definition.
   Returns the best matching persona + confidence score.
--------------------------------------------------------- */
function matchPersona(candidate) {
    const roleText   = (candidate.role || "").toLowerCase();
    const skillText  = (typeof candidate.skills === "string"
        ? candidate.skills
        : Array.isArray(candidate.skills)
            ? candidate.skills.join(" ")
            : ""
    ).toLowerCase();
    const whyText    = (candidate.why || candidate.explanation || "").toLowerCase();
    const allText    = `${roleText} ${skillText} ${whyText}`;

    const scores = PERSONA_DEFINITIONS.map(persona => {
        let score = 0;

        // Role signal matching (weight: 3)
        persona.roleSignals.forEach(signal => {
            if (roleText.includes(signal)) score += 3;
        });

        // Skill signal matching (weight: 2)
        persona.skillSignals.forEach(signal => {
            if (allText.includes(signal)) score += 2;
        });

        // Trait matching (weight: 1)
        persona.traits.forEach(trait => {
            if (allText.includes(trait)) score += 1;
        });

        return { persona, score };
    });

    // Sort by score descending
    scores.sort((a, b) => b.score - a.score);

    const top = scores[0];
    const second = scores[1];
    const total = scores.reduce((sum, s) => sum + s.score, 0);

    // Confidence = top score / total signals possible
    const maxPossible = top.persona.roleSignals.length * 3 +
                        top.persona.skillSignals.length * 2 +
                        top.persona.traits.length;

    const confidence = total > 0
        ? Math.min(100, Math.round((top.score / Math.max(maxPossible, 1)) * 100 + 40))
        : 50;

    return {
        primary: top.persona,
        secondary: second ? second.persona : null,
        confidence: Math.min(confidence, 99),
        allScores: scores
    };
}

/* ---------------------------------------------------------
   15.3 — CLUSTER ANALYZER
   Takes all candidates and groups them into persona clusters.
   Returns cluster summary with counts and fit percentages.
--------------------------------------------------------- */
function analyzePersonaClusters(candidates) {
    const clusters = {};

    PERSONA_DEFINITIONS.forEach(p => {
        clusters[p.id] = { persona: p, candidates: [], count: 0 };
    });

    candidates.forEach(candidate => {
        const match = matchPersona(candidate);
        const id = match.primary.id;
        clusters[id].candidates.push({ ...candidate, personaMatch: match });
        clusters[id].count++;
    });

    // Sort by count descending, filter empty
    return Object.values(clusters)
        .filter(c => c.count > 0)
        .sort((a, b) => b.count - a.count);
}

/* ---------------------------------------------------------
   15.4 — PERSONA EXPLANATION GENERATOR
   Creates a natural language explanation of why a candidate
   matches a specific persona.
--------------------------------------------------------- */
function generatePersonaExplanation(candidate, persona) {
    const roleText  = (candidate.role || "").toLowerCase();
    const matchedSignals = persona.roleSignals.filter(s => roleText.includes(s));

    if (matchedSignals.length > 0) {
        return `Their ${candidate.role || "background"} maps directly to the ${persona.name} archetype — ${persona.tagline.toLowerCase()}.`;
    }

    return `Based on their trajectory and skill profile, they exhibit strong ${persona.name} characteristics: ${persona.description.split(".")[0].toLowerCase()}.`;
}

/* ---------------------------------------------------------
   15.5 — RENDER PERSONA MATCH TAG
   Adds a small persona badge to existing candidate cards.
   Call after cards are already rendered.
--------------------------------------------------------- */
function attachPersonaTagsToCards() {
    const cards = document.querySelectorAll(".result-card, .pro-candidate-card, .ctc");
    cards.forEach(card => {
        const nameEl = card.querySelector(".result-name, .pro-candidate-name, .ctc-name");
        const roleEl = card.querySelector(".result-tier, .pro-candidate-role, .ctc-role");

        if (!nameEl || card.querySelector(".persona-tag")) return;

        const candidate = {
            name: nameEl.textContent,
            role: roleEl ? roleEl.textContent : ""
        };

        const match = matchPersona(candidate);
        if (!match.primary) return;

        const tag = document.createElement("span");
        tag.className = `persona-tag ${match.primary.color}`;
        tag.textContent = `${match.primary.icon} ${match.primary.name}`;
        nameEl.parentNode.insertBefore(tag, nameEl.nextSibling);
    });
}

/* ---------------------------------------------------------
   15.6 — RENDER PERSONA CLUSTERS PANEL
   Main panel showing all detected persona clusters
   with candidate counts and fit breakdown.
--------------------------------------------------------- */
function renderPersonaClusters(candidates) {
    const container = document.getElementById("personaMatchPanel");
    if (!container) return;

    const clusters = analyzePersonaClusters(candidates);

    if (!clusters.length) {
        container.style.display = "none";
        return;
    }

    container.style.display = "block";
    container.innerHTML = "";

    // Panel title
    const title = document.createElement("div");
    title.className = "pro-panel-title";
    title.textContent = "AI Persona Matching";
    container.appendChild(title);

    // Subtitle
    const sub = document.createElement("div");
    sub.className = "persona-panel-sub";
    sub.textContent = `${candidates.length} candidate${candidates.length !== 1 ? "s" : ""} clustered across ${clusters.length} persona${clusters.length !== 1 ? "s" : ""}`;
    container.appendChild(sub);

    // Cluster grid
    const grid = document.createElement("div");
    grid.className = "persona-cluster-grid";
    container.appendChild(grid);

    clusters.forEach((cluster, i) => {
        const p = cluster.persona;
        const card = document.createElement("div");
        card.className = `persona-cluster-card ${p.color}-card kinetic-settle`;
        card.style.animationDelay = `${i * 0.1}s`;

        // Header
        const header = document.createElement("div");
        header.className = "persona-cluster-header";
        header.innerHTML = `
            <span class="persona-cluster-icon ${p.color}">${p.icon}</span>
            <div class="persona-cluster-info">
                <div class="persona-cluster-name">${p.name}</div>
                <div class="persona-cluster-tagline">${p.tagline}</div>
            </div>
            <div class="persona-cluster-count">${cluster.count}</div>
        `;
        card.appendChild(header);

        // Description
        const desc = document.createElement("div");
        desc.className = "persona-cluster-desc";
        desc.textContent = p.description;
        card.appendChild(desc);

        // Candidate list inside this cluster
        if (cluster.candidates.length > 0) {
            const list = document.createElement("div");
            list.className = "persona-cluster-candidates";

            cluster.candidates.forEach(c => {
                const item = document.createElement("div");
                item.className = "persona-cluster-candidate-row";
                item.innerHTML = `
                    <span class="persona-candidate-name">${c.name || "Candidate"}</span>
                    <span class="persona-candidate-confidence">${c.personaMatch.confidence}% fit</span>
                `;
                list.appendChild(item);
            });

            card.appendChild(list);
        }

        // Trait pills
        const traits = document.createElement("div");
        traits.className = "persona-trait-pills";
        p.traits.slice(0, 4).forEach(trait => {
            const pill = document.createElement("span");
            pill.className = `persona-trait-pill ${p.color}-pill`;
            pill.textContent = trait;
            traits.appendChild(pill);
        });
        card.appendChild(traits);

        grid.appendChild(card);
    });
}

/* ---------------------------------------------------------
   15.7 — RENDER PERSONA MATCH CARDS
   Individual detailed cards for each candidate
   showing their persona match with confidence + explanation.
--------------------------------------------------------- */
function renderPersonaMatchCards(candidates) {
    const container = document.getElementById("personaMatchCards");
    if (!container) return;

    container.style.display = "block";
    container.innerHTML = "";

    const title = document.createElement("div");
    title.className = "pro-panel-title";
    title.textContent = "Candidate Persona Profiles";
    container.appendChild(title);

    const grid = document.createElement("div");
    grid.className = "persona-match-grid";
    container.appendChild(grid);

    candidates.forEach((candidate, i) => {
        const match = matchPersona(candidate);
        const p = match.primary;
        const explanation = generatePersonaExplanation(candidate, p);

        const card = document.createElement("div");
        card.className = `persona-match-card kinetic-settle`;
        card.style.animationDelay = `${i * 0.12}s`;

        card.innerHTML = `
            <div class="persona-match-header">
                <div class="persona-match-icon-wrap ${p.color}">
                    <span class="persona-match-icon">${p.icon}</span>
                </div>
                <div class="persona-match-info">
                    <div class="persona-match-candidate">${candidate.name || "Candidate"}</div>
                    <div class="persona-match-role">${candidate.role || ""}</div>
                </div>
                <div class="persona-match-confidence-wrap">
                    <div class="persona-match-confidence-val">${match.confidence}%</div>
                    <div class="persona-match-confidence-label">persona fit</div>
                </div>
            </div>

            <div class="persona-match-primary">
                <span class="persona-tag ${p.color}">${p.icon} ${p.name}</span>
                ${match.secondary ? `<span class="persona-tag-secondary">also: ${match.secondary.icon} ${match.secondary.name}</span>` : ""}
            </div>

            <div class="persona-match-explanation">${explanation}</div>

            <div class="persona-match-bar-wrap">
                <div class="persona-match-bar">
                    <div class="persona-match-bar-fill ${p.color}-bar" style="width:${match.confidence}%"></div>
                </div>
            </div>
        `;

        grid.appendChild(card);
    });
}

/* ---------------------------------------------------------
   15.8 — MASTER PHASE 15 RUNNER
   Call this after runPhase14() in runSearch().
--------------------------------------------------------- */
function runPhase15(candidates) {
    if (!candidates || candidates.length === 0) return;

    // Render cluster panel
    renderPersonaClusters(candidates);

    // Render individual persona match cards
    renderPersonaMatchCards(candidates);

    // Attach persona tags to existing candidate cards
    setTimeout(() => attachPersonaTagsToCards(), 300);
}