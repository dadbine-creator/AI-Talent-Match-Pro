/* ============================================================
   PHASE 18 — CANDIDATE POPUP + MOTION SYSTEM
   Click card → full popup modal
   Arrow navigation · Keyboard support · Counter
   ============================================================ */

/* ---------------------------------------------------------
   18.1 — POPUP STATE
--------------------------------------------------------- */
let p18CurrentCandidates = [];
let p18CurrentIndex = 0;
let p18PopupOverlay = null;

/* ---------------------------------------------------------
   18.2 — OPEN POPUP
--------------------------------------------------------- */
function openCandidatePopup(candidates, index) {
    p18CurrentCandidates = candidates;
    p18CurrentIndex = index;

    // Remove existing popup if any
    closeCandidatePopup(true);

    const candidate = candidates[index];
    const tierKey = detectTierKey(candidate);

    // Create overlay
    const overlay = document.createElement("div");
    overlay.className = "p18-candidate-popup-overlay";
    overlay.id = "p18PopupOverlay";

    // Create popup
    const popup = document.createElement("div");
    popup.className = "p18-candidate-popup";

    // Counter
    const counter = document.createElement("div");
    counter.className = "p18-counter";
    counter.textContent = `${index + 1} of ${candidates.length}`;
    popup.appendChild(counter);

    // Close button
    const closeBtn = document.createElement("button");
    closeBtn.className = "p18-popup-close";
    closeBtn.innerHTML = "✕";
    closeBtn.setAttribute("aria-label", "Close candidate profile");
    closeBtn.addEventListener("click", () => closeCandidatePopup());
    popup.appendChild(closeBtn);

    // Build card content inside popup
    const cardContent = buildPopupContent(candidate, tierKey);
    popup.appendChild(cardContent);

    // Prev arrow
    if (candidates.length > 1) {
        const prevBtn = document.createElement("button");
        prevBtn.className = "p18-nav-arrow p18-nav-prev";
        prevBtn.innerHTML = "‹";
        prevBtn.setAttribute("aria-label", "Previous candidate");
        prevBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            navigatePopup(-1);
        });
        popup.appendChild(prevBtn);

        // Next arrow
        const nextBtn = document.createElement("button");
        nextBtn.className = "p18-nav-arrow p18-nav-next";
        nextBtn.innerHTML = "›";
        nextBtn.setAttribute("aria-label", "Next candidate");
        nextBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            navigatePopup(1);
        });
        popup.appendChild(nextBtn);
    }

    overlay.appendChild(popup);

    // Close on overlay click
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) closeCandidatePopup();
    });

    document.body.appendChild(overlay);
    p18PopupOverlay = overlay;

    // Keyboard navigation
    document.addEventListener("keydown", handlePopupKeyboard);
}

/* ---------------------------------------------------------
   18.3 — BUILD POPUP CONTENT
--------------------------------------------------------- */
function buildPopupContent(candidate, tierKey) {
    const tierMap = {
        "100":    { label: "Gold Tier",   pctClass: "gold-pct",   cardClass: "gold-card",   trophy: "🏆", pct: "100%" },
        "90":     { label: "Silver Tier", pctClass: "silver-pct", cardClass: "silver-card", trophy: "🥈", pct: "90%" },
        "80":     { label: "Bronze Tier", pctClass: "bronze-pct", cardClass: "bronze-card", trophy: "🥉", pct: "80%" },
        "gold":   { label: "Gold Tier",   pctClass: "gold-pct",   cardClass: "gold-card",   trophy: "🏆", pct: "100%" },
        "silver": { label: "Silver Tier", pctClass: "silver-pct", cardClass: "silver-card", trophy: "🥈", pct: "90%" },
        "bronze": { label: "Bronze Tier", pctClass: "bronze-pct", cardClass: "bronze-card", trophy: "🥉", pct: "80%" },
    };

    const t = tierMap[tierKey] || tierMap["80"];
    const photoUrl = candidate.photo || "";
    const linkedinUrl = candidate.linkedin || candidate.linkedin_url || "#";
    const score = candidate.score || (tierKey === "100" || tierKey === "gold" ? 94 : tierKey === "90" || tierKey === "silver" ? 89 : 83);

    const checklist = getChecklistForTier(tierKey);

    const wrapper = document.createElement("div");
    wrapper.className = `p17-tier-card ${t.cardClass}`;
    wrapper.style.cssText = "margin:0;border:none;background:transparent;padding:0;animation:none;";

    const photoContent = photoUrl
        ? `<img class="p17-photo" src="${photoUrl}" alt="${candidate.name}" />`
        : `<div class="p17-photo p17-photo-placeholder">👤</div>`;

    const checklistHTML = checklist.map((item, i) => `
        <div class="p17-check-row${i >= 6 ? " hidden" : ""}" data-extra="${i >= 6}">
            <span class="p17-check-icon" aria-hidden="true">✓</span>
            <span>${item}</span>
        </div>
    `).join("");

    wrapper.innerHTML = `
        <div class="p17-photo-wrap" style="margin:0 auto 16px;">
            ${photoContent}
            <span class="p17-trophy" aria-hidden="true">${t.trophy}</span>
        </div>

        <div class="p17-tier-row">
            <div class="p17-tier-line"></div>
            <span class="p17-tier-label">
                <span class="${t.pctClass}-name">${t.label}</span> | <span class="${t.pctClass}">${score}%</span>
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
           href="${linkedinUrl}"
           target="_blank"
           rel="noopener noreferrer"
           aria-label="View ${candidate.name}'s LinkedIn profile">
            <span class="p17-linkedin-icon" aria-hidden="true">in</span>
            <span><strong>View LinkedIn</strong> Profile</span>
        </a>
    `;

    // Read more toggle
    const readMoreBtn = wrapper.querySelector(".p17-read-more");
    if (readMoreBtn) {
        readMoreBtn.addEventListener("click", () => {
            const expanded = readMoreBtn.dataset.expanded !== "1";
            readMoreBtn.dataset.expanded = expanded ? "1" : "0";
            readMoreBtn.setAttribute("aria-expanded", expanded);
            wrapper.querySelectorAll(".p17-check-row").forEach(row => {
                row.classList.toggle("hidden", !expanded && row.dataset.extra === "true");
            });
            readMoreBtn.textContent = expanded ? "Show less" : "Read more";
        });
    }

    return wrapper;
}

/* ---------------------------------------------------------
   18.4 — NAVIGATE POPUP
--------------------------------------------------------- */
function navigatePopup(direction) {
    const newIndex = p18CurrentIndex + direction;
    if (newIndex < 0 || newIndex >= p18CurrentCandidates.length) return;
    openCandidatePopup(p18CurrentCandidates, newIndex);
}

/* ---------------------------------------------------------
   18.5 — CLOSE POPUP
--------------------------------------------------------- */
function closeCandidatePopup(instant = false) {
    const overlay = document.getElementById("p18PopupOverlay");
    if (!overlay) return;

    if (instant) {
        overlay.remove();
    } else {
        overlay.style.animation = "p18FadeOut 160ms ease both";
        setTimeout(() => overlay.remove(), 160);
    }

    document.removeEventListener("keydown", handlePopupKeyboard);
    p18PopupOverlay = null;
}

/* ---------------------------------------------------------
   18.6 — KEYBOARD NAVIGATION
--------------------------------------------------------- */
function handlePopupKeyboard(e) {
    switch (e.key) {
        case "Escape":
            closeCandidatePopup();
            break;
        case "ArrowRight":
        case "ArrowDown":
            e.preventDefault();
            navigatePopup(1);
            break;
        case "ArrowLeft":
        case "ArrowUp":
            e.preventDefault();
            navigatePopup(-1);
            break;
    }
}

/* ---------------------------------------------------------
   18.7 — DETECT TIER KEY
--------------------------------------------------------- */
function detectTierKey(candidate) {
    if (candidate.tier === "100" || candidate.tier === "gold" || candidate.tierLabel?.toLowerCase().includes("gold")) return "gold";
    if (candidate.tier === "90" || candidate.tier === "silver" || candidate.tierLabel?.toLowerCase().includes("silver")) return "silver";
    return "bronze";
}

/* ---------------------------------------------------------
   18.8 — CHECKLIST PER TIER
--------------------------------------------------------- */
function getChecklistForTier(tier) {
    const gold = [
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
    const silver = [
        "Title closely matches the role",
        "Most core skills align",
        "Seniority is a strong fit",
        "Experience largely meets expectations",
        "Boolean relevance is strong",
        "Career trajectory is well aligned",
        "Location within target range",
        "Tenure shows good stability"
    ];
    const bronze = [
        "Title has meaningful overlap",
        "Key skills are present",
        "Seniority is reasonably aligned",
        "Experience partially meets expectations",
        "Boolean relevance is solid",
        "Career trajectory shows promise"
    ];
    if (tier === "gold" || tier === "100") return gold;
    if (tier === "silver" || tier === "90") return silver;
    return bronze;
}

/* ---------------------------------------------------------
   18.9 — MAKE TIER CARDS CLICKABLE
   Call after Phase 17 renders the cards.
--------------------------------------------------------- */
function attachCardClickHandlers(candidates) {
    setTimeout(() => {
        const cards = document.querySelectorAll(".p17-tier-card");
        cards.forEach((card, index) => {
            card.style.cursor = "pointer";
            card.setAttribute("role", "button");
            card.setAttribute("aria-label", `View ${candidates[index]?.name || "candidate"} profile`);

            card.addEventListener("click", (e) => {
                // Don't open popup if clicking LinkedIn link or read more
                if (e.target.closest(".p17-linkedin-link") || e.target.closest(".p17-read-more")) return;
                openCandidatePopup(candidates, index);
            });
        });
    }, 400);
}

/* ---------------------------------------------------------
   18.10 — PHASE 18 MASTER RUNNER
--------------------------------------------------------- */
function runPhase18(candidates) {
    if (!candidates || candidates.length === 0) return;
    attachCardClickHandlers(candidates);
}