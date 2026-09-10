/* ============================================================
   PHASE 33 — Recruiter OS + AI Outreach + Copilot
   Wires Phase 33 API into existing workspace.html
   ZERO design changes — pure functionality layer on top
   ============================================================ */

/* ---------------------------------------------------------
   33.1 — SAVE CANDIDATES TO PHASE 33 API
   Hooks into existing runSearch() after candidates render
--------------------------------------------------------- */
async function phase33SaveCandidates(candidates) {
    if (!candidates || candidates.length === 0) return;

    for (const c of candidates) {
        try {
            await fetch('/api/candidates', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name:         c.name,
                    role:         c.role || c.tierLabel || '',
                    tier:         c.tier === '100' || c.tier === 'gold'   ? 'gold'
                                : c.tier === '90'  || c.tier === 'silver' ? 'silver'
                                : 'bronze',
                    match_score:  c.score || 0,
                    adaptability: c.adaptability || 0,
                    focus_penalty:c.focus_penalty || 0,
                    ai_analysis:  c.why || c.ai_analysis || '',
                    silent_skill: c.silent_skill || '',
                    linkedin_url: c.linkedin || c.linkedin_url || '',
                    shortlisted:  false
                })
            });
        } catch(e) {
            // Silent fail — never break existing UI
        }
    }
}

/* ---------------------------------------------------------
   33.2 — CREATE PROJECT FOR ACTIVE ROLE
   Called after role creation — creates a pipeline project
--------------------------------------------------------- */
async function phase33CreateProject(roleTitle, roleLocation, rolePriority) {
    try {
        const res = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name:        roleTitle,
                description: roleLocation || '',
                priority:    rolePriority || 'medium'
            })
        });
        const data = await res.json();
        if (data.ok) {
            localStorage.setItem('phase33_active_project', data.project_id);
            return data.project_id;
        }
    } catch(e) {}
    return null;
}

/* ---------------------------------------------------------
   33.3 — ADD OUTREACH BUTTON TO PHASE 17 TIER CARDS
   Patches buildP17TierCard to inject outreach button
   after LinkedIn link — zero visual change to existing card
--------------------------------------------------------- */
const _originalBuildP17TierCard = typeof buildP17TierCard === 'function' ? buildP17TierCard : null;

if (_originalBuildP17TierCard) {
    window.buildP17TierCard = function(candidate, tierKey) {
        const card = _originalBuildP17TierCard(candidate, tierKey);

        // Inject outreach button after the linkedin link
        const linkedinLink = card.querySelector('.p17-linkedin-link');
        if (linkedinLink) {
            const divider = document.createElement('div');
            divider.className = 'p17-divider';

            const outreachBtn = document.createElement('button');
            outreachBtn.className = 'p17-read-more';  // reuse existing style
            outreachBtn.setAttribute('aria-label', `Generate outreach for ${candidate.name}`);
            outreachBtn.textContent = '✉ Generate Outreach';

            outreachBtn.addEventListener('click', () => {
                phase33GenerateOutreach(candidate, outreachBtn);
            });

            linkedinLink.insertAdjacentElement('afterend', divider);
            divider.insertAdjacentElement('afterend', outreachBtn);
        }

        return card;
    };
}

/* ---------------------------------------------------------
   33.4 — GENERATE OUTREACH FOR A CANDIDATE
   Calls /api/outreach/generate and shows message on card
--------------------------------------------------------- */
async function phase33GenerateOutreach(candidate, btn) {
    if (!btn) return;

    // Find candidate ID from saved candidates
    let candidateId = null;
    try {
        const res  = await fetch('/api/candidates');
        const data = await res.json();
        if (data.ok && data.candidates) {
            const match = data.candidates.find(c =>
                c.name.toLowerCase() === candidate.name.toLowerCase()
            );
            if (match) candidateId = match.id;
        }
    } catch(e) {}

    if (!candidateId) {
        btn.textContent = '✉ Save candidate first';
        setTimeout(() => { btn.textContent = '✉ Generate Outreach'; }, 2000);
        return;
    }

    btn.textContent = '⏳ Generating...';
    btn.disabled = true;

    try {
        const res  = await fetch('/api/outreach/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                candidate_id:  candidateId,
                message_type:  'linkedin_connection',
                tone:          'warm',
                project_id:    localStorage.getItem('phase33_active_project') || null
            })
        });
        const data = await res.json();

        if (data.ok) {
            // Show message in a new block on the card
            const card = btn.closest('.p17-tier-card');
            if (card) {
                // Remove existing outreach block if any
                const existing = card.querySelector('.p33-outreach-block');
                if (existing) existing.remove();

                const block = document.createElement('div');
                block.className = 'p33-outreach-block';
                block.style.cssText = 'margin-top:10px;padding:12px;border-radius:8px;background:rgba(29,110,245,0.08);border:1px solid rgba(29,110,245,0.2);font-size:12px;line-height:1.6;color:inherit;';

                block.innerHTML = `
                    <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px;opacity:0.6;">AI Generated · LinkedIn</div>
                    <div class="p33-outreach-text">${data.message}</div>
                    <div style="display:flex;gap:8px;margin-top:8px;">
                        <button onclick="navigator.clipboard.writeText(this.closest('.p33-outreach-block').querySelector('.p33-outreach-text').textContent).then(()=>{this.textContent='✓ Copied';setTimeout(()=>this.textContent='📋 Copy',1500)})"
                            style="font-size:11px;padding:4px 10px;border-radius:6px;border:1px solid rgba(255,255,255,0.12);background:transparent;cursor:pointer;color:inherit;">
                            📋 Copy
                        </button>
                        <button onclick="phase33MarkSent('${data.outreach_id}',this)"
                            style="font-size:11px;padding:4px 10px;border-radius:6px;border:1px solid rgba(255,255,255,0.12);background:transparent;cursor:pointer;color:inherit;">
                            ✓ Mark Sent
                        </button>
                    </div>
                    <div style="font-size:10px;opacity:0.45;margin-top:6px;">${data.char_count} chars · Quality: ${data.quality_score}/100 · $${(data.cost_usd||0).toFixed(4)}</div>
                `;

                btn.insertAdjacentElement('afterend', block);
            }

            btn.textContent = '✉ Regenerate';
            btn.disabled = false;
        } else {
            btn.textContent = '✉ Try again';
            btn.disabled = false;
        }
    } catch(e) {
        btn.textContent = '✉ Generate Outreach';
        btn.disabled = false;
    }
}

/* ---------------------------------------------------------
   33.5 — MARK OUTREACH AS SENT
--------------------------------------------------------- */
async function phase33MarkSent(outreachId, btn) {
    if (!outreachId || !btn) return;
    try {
        await fetch(`/api/outreach/${outreachId}/sent`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sent_via: 'linkedin' })
        });
        btn.textContent = '✓ Sent';
        btn.style.color = '#00d68f';
    } catch(e) {}
}

/* ---------------------------------------------------------
   33.6 — WIRE COPILOT INTO RIGHT PANEL AI STREAM
   Adds a copilot input below the existing AI stream
   Uses existing class names from your CSS — no new styles
--------------------------------------------------------- */
function phase33InjectCopilot() {
    const aiStream = document.querySelector('.ai-stream');
    if (!aiStream) return;

    // Don't inject twice
    if (document.getElementById('p33CopilotInput')) return;

    const copilotWrap = document.createElement('div');
    copilotWrap.style.cssText = 'padding:12px 0 4px;';

    copilotWrap.innerHTML = `
        <div class="ai-stream-label">Recruiter Copilot</div>
        <div id="p33CopilotOutput" style="margin-bottom:8px;"></div>
        <div style="display:flex;gap:6px;">
            <input id="p33CopilotInput"
                   type="text"
                   placeholder="Ask copilot anything..."
                   class="modal-input"
                   style="flex:1;padding:8px 12px;font-size:12px;border-radius:8px;"
                   onkeydown="if(event.key==='Enter')phase33RunCopilot()" />
            <button onclick="phase33RunCopilot()"
                    class="primary-button"
                    style="padding:8px 14px;font-size:12px;min-width:unset;">
                ↗
            </button>
        </div>
    `;

    aiStream.appendChild(copilotWrap);
}

/* ---------------------------------------------------------
   33.7 — RUN COPILOT SESSION
--------------------------------------------------------- */
async function phase33RunCopilot() {
    const input  = document.getElementById('p33CopilotInput');
    const output = document.getElementById('p33CopilotOutput');
    if (!input || !output) return;

    const prompt = input.value.trim();
    if (!prompt) return;
    input.value = '';

    // Show thinking state using existing ai-line style
    const thinking = document.createElement('div');
    thinking.className = 'ai-line-cinematic';
    thinking.textContent = '› Copilot thinking...';
    thinking.style.opacity = '0.5';
    output.appendChild(thinking);

    try {
        const res  = await fetch('/api/copilot/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt,
                session_type: 'next_best_action',
                project_id:   localStorage.getItem('phase33_active_project') || null
            })
        });
        const data = await res.json();
        thinking.remove();

        if (data.ok) {
            const line = document.createElement('div');
            line.className = 'ai-line-cinematic';
            line.style.cssText = 'padding:10px;border-radius:8px;background:rgba(29,110,245,0.07);border:1px solid rgba(29,110,245,0.15);margin-bottom:6px;font-size:12px;line-height:1.6;';
            line.innerHTML = `
                <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:5px;opacity:0.55;">Copilot · ${data.type_label||'Analysis'}</div>
                <div>${data.response.slice(0,350)}${data.response.length>350?'...':''}</div>
                <div style="display:flex;gap:6px;margin-top:8px;">
                    <button onclick="phase33CopilotFeedback('${data.session_id}',true,this)"
                        style="font-size:10px;padding:2px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.12);background:transparent;cursor:pointer;color:inherit;">👍</button>
                    <button onclick="phase33CopilotFeedback('${data.session_id}',false,this)"
                        style="font-size:10px;padding:2px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.12);background:transparent;cursor:pointer;color:inherit;">👎</button>
                </div>
            `;
            output.appendChild(line);

            // Scroll ai stream
            const aiStream = document.querySelector('.ai-stream');
            if (aiStream) aiStream.scrollTop = aiStream.scrollHeight;
        }
    } catch(e) {
        thinking.textContent = '› Copilot temporarily unavailable';
        thinking.style.opacity = '0.4';
    }
}

/* ---------------------------------------------------------
   33.8 — COPILOT FEEDBACK
--------------------------------------------------------- */
async function phase33CopilotFeedback(sessionId, helpful, btn) {
    try {
        await fetch(`/api/copilot/${sessionId}/feedback`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ helpful, acted_on: false })
        });
        if (btn) { btn.style.opacity = '1'; btn.style.fontWeight = '700'; }
    } catch(e) {}
}

/* ---------------------------------------------------------
   33.9 — HOOK INTO EXISTING SEARCH FLOW
   Patches runPhase17 to also save candidates + create project
--------------------------------------------------------- */
const _originalRunPhase17 = typeof runPhase17 === 'function' ? runPhase17 : null;

if (_originalRunPhase17) {
    window.runPhase17 = function(candidates) {
        // Run original Phase 17 first — zero change
        _originalRunPhase17(candidates);

        // Then add Phase 33 on top
        phase33SaveCandidates(candidates);

        // Create project if there's an active role
        const activeRoleId = typeof getActiveRoleId === 'function' ? getActiveRoleId() : null;
        if (activeRoleId) {
            const roles = typeof loadAllRoles === 'function' ? loadAllRoles() : [];
            const role = roles.find(r => r.id === activeRoleId);
            if (role && role.title) {
                phase33CreateProject(role.title, role.location, 'medium');
            }
        }
    };
}

/* ---------------------------------------------------------
   33.10 — HOOK SHORTLIST FEEDBACK INTO PHASE 33 API
   Patches recordFeedback to also call /api/feedback
--------------------------------------------------------- */
const _originalRecordFeedback = typeof recordFeedback === 'function' ? recordFeedback : null;

if (_originalRecordFeedback) {
    window.recordFeedback = function(candidateName, role, sentiment) {
        // Run original first
        _originalRecordFeedback(candidateName, role, sentiment);

        // Also send to Phase 33 API
        const signal = sentiment === 'up' ? 'shortlist' : 'skip';
        fetch('/api/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action:         signal,
                candidate_name: candidateName,
                job_title:      role,
                tier:           null,
                match_score:    null
            })
        }).catch(() => {});  // Silent fail — never break existing UI
    };
}

/* ---------------------------------------------------------
   33.11 — INIT
   Inject copilot after DOM is ready
--------------------------------------------------------- */
function phase33Init() {
    phase33InjectCopilot();
}

// Wait for existing DOMContentLoaded to finish first
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(phase33Init, 500));
} else {
    setTimeout(phase33Init, 500);
}