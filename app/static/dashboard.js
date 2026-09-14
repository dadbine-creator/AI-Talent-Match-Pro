/* ============================================================
   AI Talent Match Pro — Main Controller (Phases 1–17)
   ============================================================ */

const aiLines = document.getElementById("aiLines");
const booleanBox = document.getElementById("booleanBox");
const booleanText = document.getElementById("booleanText");
const resultsGrid = document.getElementById("resultsGrid");
const searchBtn = document.getElementById("searchBtn");
const newSessionBtn = document.getElementById("newSessionBtn");
const sidebarList = document.getElementById("sidebarList");
const welcomeTitle = document.getElementById("welcomeTitle");

const positionTitleInput = document.getElementById("positionTitle");
const jobDescriptionInput = document.getElementById("jobDescription");
const locationInput = document.getElementById("location");
const skillsInput = document.getElementById("skills");

const centerPanel = document.querySelector(".center-panel");
const formCard = document.querySelector(".form-card");

const centerEmpty = document.getElementById("centerEmpty");
const formCardEl = document.getElementById("formCard");
const emptyStartBtn = document.getElementById("emptyStartBtn");

const proDashboard = document.getElementById("proDashboard");
const kpiGrid = document.getElementById("kpiGrid");
const scoreRingValue = document.getElementById("scoreRingValue");
const scoreBarFill = document.getElementById("scoreBarFill");
const insightsBody = document.getElementById("insightsBody");
const proCandidateGrid = document.getElementById("proCandidateGrid");

const marketDensityList = document.getElementById("marketDensityList");
const salaryCurveList = document.getElementById("salaryCurveList");
const seniorityList = document.getElementById("seniorityList");
const personaGrid = document.getElementById("personaGrid");
const trajectoryList = document.getElementById("trajectoryList");
const competitivenessScore = document.getElementById("competitivenessScore");
const trendList = document.getElementById("trendList");

/* ---------------------------------------------------------
   EMPTY STATES
--------------------------------------------------------- */
function clearIntelligentEmptyStates() {
    document.querySelectorAll(".empty-intelligent").forEach(el => el.remove());
}

function createEmptyBlock(variantClass, text, container) {
    const div = document.createElement("div");
    div.className = `empty-intelligent ${variantClass} parallax-idle`;
    div.textContent = text;
    container.appendChild(div);
    return div;
}

function setWorkspaceEmpty() {
    if (centerPanel) centerPanel.classList.add("workspace-breathe");
    if (formCard) formCard.classList.add("cyan-glow", "parallax-idle", "glow-reveal");
}

function setWorkspaceActive() {
    if (centerPanel) centerPanel.classList.remove("workspace-breathe");
    if (formCard) formCard.classList.remove("cyan-glow", "parallax-idle", "glow-reveal");
    clearIntelligentEmptyStates();
}

function fadeInElement(el) {
    el.style.opacity = "0";
    el.style.transform = "translateY(6px)";
    el.style.transition = "opacity 0.35s ease, transform 0.35s ease";
    requestAnimationFrame(() => {
        el.style.opacity = "1";
        el.style.transform = "translateY(0)";
    });
}

function showEmptyState() {
    aiLines.innerHTML = "";
    resultsGrid.innerHTML = "";
    booleanBox.style.display = "none";
    clearIntelligentEmptyStates();

    if (centerEmpty) centerEmpty.style.display = "block";
    if (formCardEl) formCardEl.style.display = "none";
    if (proDashboard) proDashboard.style.display = "none";

    const tierCardsContainer = document.getElementById("tierCardsContainer");
    if (tierCardsContainer) tierCardsContainer.innerHTML = "";

    const msg = document.createElement("div");
    msg.textContent = "Your workspace is ready. Define a role or open a saved search to begin.";
    msg.classList.add("ai-line-faded");
    aiLines.appendChild(msg);
    fadeInElement(msg);

    createEmptyBlock("empty-ai", "No active role yet. Start by shaping the role on the right.", aiLines);
    setWorkspaceEmpty();
}

function updateSidebarEmptyState(hasRoles) {
    const emptySidebar = document.getElementById("emptySidebar");
    if (!emptySidebar) return;
    emptySidebar.style.display = hasRoles ? "none" : "block";
}

function scrollActiveSidebarCardIntoView() {
    const active = document.querySelector(".sidebar-card.active");
    if (active) active.scrollIntoView({ behavior: "smooth", block: "center" });
}

/* ---------------------------------------------------------
   LOAD HR NAME + IDENTITY
--------------------------------------------------------- */
async function loadHRName() {
    try {
        const response = await fetch("/me");
        const data = await response.json();
        welcomeTitle.textContent = data.ok && data.name ? `Welcome back, ${data.name}` : "Welcome back";
    } catch {
        welcomeTitle.textContent = "Welcome back";
    }
}

async function loadSidebarIdentity() {
    try {
        const res = await fetch("/me");
        const data = await res.json();
        const avatarEl = document.getElementById("sidebarAvatar");
        const nameEl = document.getElementById("sidebarUserName");
        if (avatarEl && data && data.photo) avatarEl.src = data.photo;
        if (nameEl && data && data.name) nameEl.textContent = data.name;
    } catch {}
}

/* ---------------------------------------------------------
   TROPHIES
--------------------------------------------------------- */
const TROPHIES = { gold: "🥇", silver: "🥈", bronze: "🥉" };

/* ---------------------------------------------------------
   AI STREAM
--------------------------------------------------------- */
function typeTextIntoElement(el, text, onDone) {
    const chars = text.split("");
    let i = 0;

    function step() {
        if (i >= chars.length) {
            el.classList.remove("cursor");
            if (typeof onDone === "function") onDone();
            return;
        }
        const ch = chars[i++];
        el.textContent += ch;
        aiLines.scrollTop = aiLines.scrollHeight;
        let delay = 26 + Math.random() * 32;
        if (/[.,!?]/.test(ch)) delay += 260;
        if (Math.random() < 0.08) delay += 120 + Math.random() * 120;
        setTimeout(step, delay);
    }

    el.classList.add("cursor");
    step();
}

function pushAILine(text, faded = false, delayMs = 0, streaming = true) {
    setTimeout(() => {
        const div = document.createElement("div");
        if (faded) div.classList.add("ai-line-faded");
        div.classList.add("ai-line-cinematic");
        div.style.opacity = "0";
        div.style.transform = "translateY(8px)";
        div.style.transition = "opacity 0.45s ease, transform 0.45s ease";
        aiLines.appendChild(div);

        const reveal = () => {
            div.style.opacity = "1";
            div.style.transform = "translateY(0)";
            aiLines.scrollTop = aiLines.scrollHeight;
        };

        if (streaming) {
            div.classList.add("ai-thinking");
            div.textContent = "› ";
            reveal();
            typeTextIntoElement(div, text, () => div.classList.remove("ai-thinking"));
        } else {
            div.textContent = "› " + text;
            reveal();
        }
    }, delayMs);
}

function setBooleanProcessing(isProcessing) {
    if (!booleanBox) return;
    if (isProcessing) {
        booleanBox.classList.add("processing", "kinetic-glow", "kinetic-breathe");
    } else {
        booleanBox.classList.remove("processing", "kinetic-glow", "kinetic-breathe");
    }
}

/* ---------------------------------------------------------
   BOOLEAN ENGINE
--------------------------------------------------------- */
function expandTitle(role) {
    const base = role.trim();
    const lower = base.toLowerCase();
    const variants = [base];
    if (lower.includes("marketing")) {
        variants.push(base.replace(/manager/i, "Lead"), base.replace(/manager/i, "Director"), "Growth Marketing Manager", "Demand Generation Manager");
    }
    if (lower.includes("product")) {
        variants.push(base.replace(/manager/i, "Lead"), base.replace(/manager/i, "Director"), "Senior Product Manager", "Group Product Manager");
    }
    if (lower.includes("sales")) {
        variants.push(base.replace(/manager/i, "Lead"), base.replace(/manager/i, "Director"), "Account Executive", "Business Development Manager");
    }
    return Array.from(new Set(variants));
}

function expandSkills(skills) {
    if (!skills) return [];
    const raw = skills.split(",").map(s => s.trim()).filter(Boolean);
    const expanded = [];
    raw.forEach(skill => {
        const lower = skill.toLowerCase();
        expanded.push(skill);
        if (lower === "seo") expanded.push("Search Engine Optimization", "Organic Growth");
        if (lower.includes("content")) expanded.push("Content Strategy", "Content Marketing");
        if (lower.includes("paid")) expanded.push("Paid Media", "Performance Marketing");
        if (lower.includes("python")) expanded.push("Python Programming", "Data Pipelines");
        if (lower.includes("llm") || lower.includes("gpt")) expanded.push("Large Language Models", "Generative AI");
    });
    return Array.from(new Set(expanded));
}

function expandLocation(location) {
    const base = location.trim();
    const lower = base.toLowerCase();
    const variants = [base];
    if (lower.includes("new york")) variants.push("NYC", "Manhattan", "Brooklyn", "Queens");
    if (lower.includes("san francisco")) variants.push("SF", "Bay Area", "Silicon Valley");
    if (lower.includes("london")) variants.push("Greater London");
    return Array.from(new Set(variants));
}

function buildBooleanQuery(role, skills, location) {
    const titles = expandTitle(role);
    const skillGroup = expandSkills(skills);
    const locations = expandLocation(location);
    const titleClause = titles.length ? `(title:${titles.map(t => `"${t}"`).join(" OR ")})` : "";
    const skillsClause = skillGroup.length ? `(${skillGroup.map(s => `"${s}"`).join(" OR ")})` : "";
    const locationClause = locations.length ? `(location:${locations.map(l => `"${l}"`).join(" OR ")})` : "";
    const seniorityClause = `(title:("Senior" OR "Lead" OR "Head" OR "Director"))`;
    const exclusionClause = `NOT ("Intern" OR "Assistant" OR "Junior")`;
    return [titleClause, skillsClause, locationClause, seniorityClause, exclusionClause].filter(Boolean).join(" AND ");
}

/* ---------------------------------------------------------
   CANDIDATE CARDS
--------------------------------------------------------- */
function generateExplanation(tier) {
    if (tier === "Gold") return "This candidate aligns closely with your expanded title cluster, seniority, and core skill set.";
    if (tier === "Silver") return "They overlap strongly with your broader skill and title groups.";
    return "They come from a related path captured by your wider boolean cluster.";
}

function applyResultKinetics(card, index) {
    card.classList.add("card-stagger", "kinetic-settle", "kinetic-smooth");
    card.style.animationDelay = `${index * 0.1}s`;
}

function createCandidateCard(person) {
    const card = document.createElement("div");
    card.className = "result-card fade-slide-up";
    const displayScore = person.match_score || (typeof person.score === "number" ? `${person.score}/100` : "Match");
    const tier = person.tier || "Match";
    const trophy = person.trophy || "";
    const photoUrl = person.photo || "/static/profile_placeholder.png";
    const linkedinUrl = person.linkedin || person.linkedin_url || "#";
    const whyText = person.why || person.explanation || person.ai_analysis || generateExplanation(tier);
    let skillsBlock = "";
    if (Array.isArray(person.skills) && person.skills.length > 0) skillsBlock = person.skills.join(", ");
    else if (typeof person.skills === "string" && person.skills.trim()) skillsBlock = person.skills.trim();

    card.innerHTML = `
        <div class="candidate-score-line"><span class="candidate-score">${displayScore}</span></div>
        <div class="result-header">
            <div class="profile-photo-wrapper">
                <img class="result-photo" src="${photoUrl}" alt="${person.name || "Candidate"}" />
                ${trophy ? `<span class="trophy-badge">${trophy}</span>` : ""}
            </div>
            <div class="result-header-text">
                <div class="result-name">${person.name || "Unnamed Candidate"}</div>
                <div class="result-tier">${tier} Tier</div>
            </div>
        </div>
        <div class="result-section">
            <div class="result-section-title">Why this profile</div>
            <div class="result-section-body">${whyText}</div>
        </div>
        ${skillsBlock ? `<div class="result-section"><div class="result-section-title">Key skills</div><div class="result-section-body">${skillsBlock}</div></div>` : ""}
        <a class="result-link" href="${linkedinUrl}" target="_blank" rel="noopener noreferrer">View LinkedIn →</a>
    `;
    return card;
}

function primeWorkspaceKinetics() {
    if (centerPanel) centerPanel.classList.add("kinetic-smooth");
    if (formCard) formCard.classList.add("kinetic-smooth");
    if (resultsGrid) resultsGrid.classList.add("kinetic-smooth");
}

/* ---------------------------------------------------------
   MEMORY & ROLE INTELLIGENCE
--------------------------------------------------------- */
function createRoleSchema({ id, title, description, location, skills, boolean, aiStream, candidates } = {}) {
    return {
        id: id || (crypto.randomUUID ? crypto.randomUUID() : `role_${Date.now()}`),
        title: title || "", description: description || "", location: location || "",
        skills: skills || "", boolean: boolean || "",
        aiStream: Array.isArray(aiStream) ? aiStream : [],
        candidates: Array.isArray(candidates) ? candidates : [],
        createdAt: Date.now(), updatedAt: Date.now(), active: false
    };
}

const STORAGE_KEY = "atmpro_roles";

function loadAllRoles() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); } catch { return []; }
}

function saveAllRoles(list) { localStorage.setItem(STORAGE_KEY, JSON.stringify(list)); }

function saveRoleToStorage(roleObj) {
    const list = loadAllRoles();
    list.push(roleObj);
    saveAllRoles(list);
    return roleObj;
}

function updateRole(id, updates) {
    const list = loadAllRoles();
    const idx = list.findIndex(r => r.id === id);
    if (idx === -1) return;
    list[idx] = { ...list[idx], ...updates, updatedAt: Date.now() };
    saveAllRoles(list);
    return list[idx];
}

function deleteRole(id) { saveAllRoles(loadAllRoles().filter(r => r.id !== id)); }

function setActiveRole(id) {
    saveAllRoles(loadAllRoles().map(r => ({ ...r, active: r.id === id })));
    localStorage.setItem("activeRoleId", id);
}

function getActiveRoleId() { return localStorage.getItem("activeRoleId"); }

function getActiveRole() {
    const id = getActiveRoleId();
    if (!id) return null;
    return loadAllRoles().find(r => r.id === id) || null;
}

function renderSidebarFromStorage() {
    const list = loadAllRoles();
    const container = document.getElementById("sidebarList");
    const emptyState = document.getElementById("emptySidebar");
    if (!container) return;
    container.innerHTML = "";
    updateSidebarEmptyState(list.length > 0);
    if (!list.length) { if (emptyState) emptyState.style.display = "block"; return; }
    if (emptyState) emptyState.style.display = "none";
    const activeId = getActiveRoleId();
    list.forEach(role => {
        const card = document.createElement("div");
        card.className = "sidebar-card";
        if (role.id === activeId) card.classList.add("active");
        const formattedDate = new Date(role.updatedAt || role.createdAt).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
        card.innerHTML = `
            <div class="sidebar-card-main">
                <div class="sidebar-card-title">${role.title || "Untitled Role"}</div>
                <div class="sidebar-card-sub">${role.location || "No location"}</div>
                <div class="sidebar-card-meta">Updated • ${formattedDate}</div>
            </div>
            <button class="sidebar-delete-btn" data-id="${role.id}">×</button>
        `;
        card.addEventListener("click", () => { setActiveRole(role.id); renderSidebarFromStorage(); loadRoleIntoWorkspace(role); scrollActiveSidebarCardIntoView(); });
        const deleteBtn = card.querySelector(".sidebar-delete-btn");
        deleteBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            deleteRole(role.id);
            if (getActiveRoleId() === role.id) { localStorage.removeItem("activeRoleId"); showEmptyState(); }
            renderSidebarFromStorage();
        });
        container.appendChild(card);
    });
}

function loadRoleIntoWorkspace(role) {
    if (!role) return;
    if (centerEmpty) centerEmpty.style.display = "none";
    if (formCardEl) formCardEl.style.display = "block";
    setWorkspaceActive();
    positionTitleInput.value = role.title || "";
    jobDescriptionInput.value = role.description || "";
    locationInput.value = role.location || "";
    skillsInput.value = role.skills || "";
    if (role.boolean && role.boolean.trim()) { booleanText.textContent = role.boolean; booleanBox.style.display = "block"; }
    else { booleanText.textContent = ""; booleanBox.style.display = "none"; }
    aiLines.innerHTML = "";
    if (Array.isArray(role.aiStream) && role.aiStream.length > 0) {
        role.aiStream.forEach(line => {
            const div = document.createElement("div");
            div.classList.add("ai-line-cinematic");
            div.textContent = "› " + line;
            aiLines.appendChild(div);
        });
    } else {
        const msg = document.createElement("div");
        msg.textContent = "This role has no AI analysis yet. Run a search to generate insights.";
        msg.classList.add("ai-line-faded");
        aiLines.appendChild(msg);
    }
    resultsGrid.innerHTML = "";
    if (Array.isArray(role.candidates) && role.candidates.length > 0) {
        role.candidates.forEach((person, index) => {
            const card = createCandidateCard(person);
            applyResultKinetics(card, index);
            resultsGrid.appendChild(card);
        });
    }
    aiLines.scrollTop = aiLines.scrollHeight;
}

const createRoleModal = document.getElementById("createRoleModal");
const openCreateRoleModal = document.getElementById("openCreateRoleModal");
const createRoleBtn = document.getElementById("createRoleBtn");

if (openCreateRoleModal && createRoleModal) {
    openCreateRoleModal.addEventListener("click", () => { createRoleModal.style.display = "flex"; });
    createRoleModal.addEventListener("click", (e) => { if (e.target === createRoleModal) createRoleModal.style.display = "none"; });
}

// Close button
const closeRoleModal = document.getElementById("closeRoleModal");
if (closeRoleModal) {
    closeRoleModal.addEventListener("click", () => { createRoleModal.style.display = "none"; });
}

// Advanced filters toggle
const advancedToggle = document.getElementById("advancedToggle");
const advancedFilters = document.getElementById("advancedFilters");
const toggleArrow = document.getElementById("toggleArrow");
if (advancedToggle && advancedFilters) {
    advancedToggle.addEventListener("click", () => {
        const isOpen = advancedFilters.style.display !== "none";
        advancedFilters.style.display = isOpen ? "none" : "flex";
        if (toggleArrow) toggleArrow.classList.toggle("open", !isOpen);
    });
}

if (createRoleBtn && createRoleModal) {
    createRoleBtn.addEventListener("click", () => {
        const title = document.getElementById("newRoleTitle").value.trim();
        const description = document.getElementById("newRoleDescription").value.trim();
        const location = document.getElementById("newRoleLocation")?.value.trim() || "";
        const skills = document.getElementById("filterSkills")?.value.trim() || "";
        if (!title) return;
        const role = createRoleSchema({ title, description, location, skills, boolean: "", aiStream: [], candidates: [] });
        saveRoleToStorage(role);
        setActiveRole(role.id);
        renderSidebarFromStorage();
        loadRoleIntoWorkspace(role);
        createRoleModal.style.display = "none";
    });
}

/* ---------------------------------------------------------
   PRO DASHBOARD RENDERER
--------------------------------------------------------- */
function renderProDashboard(data = {}) {
    const { kpis = [], score = null, insights = "", proCandidates = [], marketDensity = [], salaryCurve = [], seniority = [], personas = [], trajectory = [], competitiveness = 0, trends = [] } = data;

    if (proDashboard) proDashboard.style.display = "block";

    if (kpiGrid) {
        kpiGrid.innerHTML = "";
        kpis.forEach(kpi => {
            const tile = document.createElement("div");
            tile.className = "kpi-tile";
            tile.innerHTML = `<div class="kpi-label">${kpi.label}</div><div class="kpi-value">${kpi.value}</div><div class="kpi-sub">${kpi.sub || ""}</div>`;
            kpiGrid.appendChild(tile);
        });
    }

    if (score !== null && scoreRingValue && scoreBarFill) {
        const safeScore = Math.max(0, Math.min(100, score));
        scoreRingValue.textContent = safeScore;
        scoreBarFill.style.width = safeScore + "%";
    }

    if (insightsBody) insightsBody.textContent = insights || "Insights will appear here after an AI search.";

    if (proCandidateGrid) {
        proCandidateGrid.innerHTML = "";
        proCandidates.forEach((person, index) => {
            const card = document.createElement("div");
            card.className = "pro-candidate-card fade-slide-up";
            card.innerHTML = `
                <div class="pro-candidate-header">
                    <div>
                        <div class="pro-candidate-name">${person.name || "Candidate"}</div>
                        <div class="pro-candidate-role">${person.role || ""}</div>
                    </div>
                    <span class="tier-badge tier-badge-${person.tier || "80"}">${person.tierLabel || (person.tier ? person.tier + " Tier" : "Tier")}</span>
                </div>
                <div class="pro-candidate-meta">
                    <span>${person.location || ""}</span>
                    <span>${person.years || ""}</span>
                </div>
                <div class="pro-candidate-score-row">
                    <div class="score-ring small"><span>${person.score || 0}</span></div>
                    <div class="score-bar small"><div class="score-bar-fill" style="width:${person.score || 0}%"></div></div>
                </div>
            `;
            applyResultKinetics(card, index);
            proCandidateGrid.appendChild(card);
        });
    }

    renderMarketDensity(marketDensity);
    renderSalaryCurve(salaryCurve);
    renderSeniority(seniority);
    renderPersonas(personas);
    renderTrajectory(trajectory);
    renderCompetitiveness(competitiveness);
    renderTrends(trends);
}

function renderMarketDensity(list = []) {
    if (!marketDensityList) return;
    marketDensityList.innerHTML = "";
    list.forEach(item => {
        const row = document.createElement("div");
        row.className = "market-density-row";
        row.innerHTML = `<div class="market-density-city">${item.city}</div><div class="market-density-bar"><div class="market-density-bar-fill" style="width:${item.score}%"></div></div><div class="market-density-score">${item.score}%</div>`;
        marketDensityList.appendChild(row);
    });
}

function renderSalaryCurve(list = []) {
    if (!salaryCurveList) return;
    salaryCurveList.innerHTML = "";
    list.forEach(item => {
        const row = document.createElement("div");
        row.className = "salary-curve-row";
        row.innerHTML = `<div class="salary-curve-label">${item.range}</div><div class="salary-curve-bar"><div class="salary-curve-bar-fill" style="width:${item.score}%"></div></div><div class="salary-curve-score">${item.score}%</div>`;
        salaryCurveList.appendChild(row);
    });
}

function renderSeniority(list = []) {
    if (!seniorityList) return;
    seniorityList.innerHTML = "";
    list.forEach(item => {
        const row = document.createElement("div");
        row.className = "seniority-row";
        row.innerHTML = `<div class="seniority-label">${item.level}</div><div class="seniority-bar"><div class="seniority-bar-fill" style="width:${item.score}%"></div></div><div class="seniority-score">${item.score}%</div>`;
        seniorityList.appendChild(row);
    });
}

function renderPersonas(list = []) {
    if (!personaGrid) return;
    personaGrid.innerHTML = "";
    list.forEach(p => {
        const card = document.createElement("div");
        card.className = "persona-card";
        card.innerHTML = `<div class="persona-name">${p.name}</div><div class="persona-desc">${p.description}</div>`;
        personaGrid.appendChild(card);
    });
}

function renderTrajectory(list = []) {
    if (!trajectoryList) return;
    trajectoryList.innerHTML = "";
    list.forEach(step => {
        const row = document.createElement("div");
        row.className = "trajectory-row";
        row.innerHTML = `<div class="trajectory-step">${step}</div>`;
        trajectoryList.appendChild(row);
    });
}

function renderCompetitiveness(score = 0) {
    if (!competitivenessScore) return;
    competitivenessScore.textContent = Math.max(0, Math.min(100, score)) + "%";
}

function renderTrends(list = []) {
    if (!trendList) return;
    trendList.innerHTML = "";
    list.forEach(item => {
        const row = document.createElement("div");
        row.className = "trend-row";
        row.innerHTML = `<div class="trend-label">${item.label}</div><div class="trend-strength">${item.strength}</div>`;
        trendList.appendChild(row);
    });
}

/* ---------------------------------------------------------
   MAIN SEARCH
--------------------------------------------------------- */
/* PHASE 21 search flow — removed.
 *
 * This called an Azure Function at ai-talent-grade-engine.azurewebsites.net
 * with the access key hardcoded here in client-side JavaScript. That Function
 * App no longer exists (the hostname does not resolve), so the call could only
 * ever fail — and on failure the code fell through to three invented people
 * (Alex Rivera, Jordan Lee, Taylor Chen) rendered as if they were candidates,
 * alongside hardcoded KPIs, market density and salary curves.
 *
 * None of it was reachable: the chain hung off a #searchBtn listener, and no
 * page contains that element, so the listener never bound. Nothing rendered
 * to a user. The real scoring flow is Team DNA, in workspace.html.
 */

if (newSessionBtn) {
    newSessionBtn.addEventListener("click", () => {
        positionTitleInput.value = "";
        jobDescriptionInput.value = "";
        locationInput.value = "";
        skillsInput.value = "";
        localStorage.removeItem("activeRoleId");
        renderSidebarFromStorage();
        showEmptyState();
    });
}

const SESSION_KEY = "atmpro_seen";
function hasSeenWorkspace() { return localStorage.getItem(SESSION_KEY) === "1"; }
function markWorkspaceSeen() { localStorage.setItem(SESSION_KEY, "1"); }

if (emptyStartBtn) {
    emptyStartBtn.addEventListener("click", () => {
        if (createRoleModal) createRoleModal.style.display = "flex";
        else { if (centerEmpty) centerEmpty.style.display = "none"; if (formCardEl) formCardEl.style.display = "block"; }
    });
}

/* ---------------------------------------------------------
   INITIAL LOAD
--------------------------------------------------------- */
document.addEventListener("DOMContentLoaded", () => {
    loadHRName();
    loadSidebarIdentity();
    primeWorkspaceKinetics();
    renderSidebarFromStorage();

    const roles = loadAllRoles();
    const active = getActiveRole();

    if (!hasSeenWorkspace() && roles.length === 0) { markWorkspaceSeen(); showEmptyState(); return; }
    if (active) { loadRoleIntoWorkspace(active); return; }
    if (roles.length > 0) {
        const sorted = [...roles].sort((a, b) => (b.updatedAt || b.createdAt) - (a.updatedAt || a.createdAt));
        const latest = sorted[0];
        if (latest) { setActiveRole(latest.id); renderSidebarFromStorage(); loadRoleIntoWorkspace(latest); return; }
    }
    showEmptyState();
});