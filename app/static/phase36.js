/* ============================================================
   PHASE 36 — NARRATIVE INTELLIGENCE
   Injects "📝 Generate Narrative" button into Phase 17
   tier cards. Sits below scorecard (Phase 35).
   Zero design changes — pure functionality layer.
   ============================================================ */

/* ---------------------------------------------------------
   36.1 — PATCH buildP17TierCard
   Adds narrative button after scorecard button
--------------------------------------------------------- */
const _p36OriginalBuildCard = typeof buildP17TierCard === 'function' ? buildP17TierCard : null;

if (_p36OriginalBuildCard) {
    window.buildP17TierCard = function(candidate, tierKey) {
        const card = _p36OriginalBuildCard(candidate, tierKey);

        const dividers = card.querySelectorAll('.p17-divider');
        const lastDivider = dividers[dividers.length - 1];

        if (lastDivider) {
            const divider = document.createElement('div');
            divider.className = 'p17-divider';

            const narrativeBtn = document.createElement('button');
            narrativeBtn.className = 'p17-read-more';
            narrativeBtn.setAttribute('aria-label', `Generate narrative for ${candidate.name}`);
            narrativeBtn.textContent = '📝 Generate Narrative';

            narrativeBtn.addEventListener('click', () => {
                p36GenerateNarrative(candidate, narrativeBtn, card);
            });

            lastDivider.insertAdjacentElement('afterend', divider);
            divider.insertAdjacentElement('afterend', narrativeBtn);
        }

        return card;
    };
}

/* ---------------------------------------------------------
   36.2 — GENERATE NARRATIVE
   Calls existing /api/narrative/generate (Phase 29)
   Enriches with scorecard data if available (Phase 35)
--------------------------------------------------------- */
async function p36GenerateNarrative(candidate, btn, card) {
    if (!btn || !card) return;

    // Get candidate ID
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

    // Get existing scorecard for alignment
    let scorecardData = null;
    if (candidateId) {
        try {
            const res  = await fetch(`/api/scorecard/candidate/${candidateId}`);
            const data = await res.json();
            if (data.ok) scorecardData = data;
        } catch(e) {}
    }

    btn.textContent = '⏳ Generating narrative...';
    btn.disabled = true;

    try {
        const res = await fetch('/api/narrative/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                candidate_id:       candidateId,
                candidate_name:     candidate.name,
                candidate_role:     candidate.role || '',
                candidate_tier:     candidate.tier || 'bronze',
                candidate_score:    candidate.score || 0,
                candidate_analysis: candidate.why || '',
                narrative_type:     'full',
                project_id:         localStorage.getItem('phase33_active_project') || null,
            })
        });
        const data = await res.json();

        // Remove existing narrative block
        const existing = card.querySelector('.p36-narrative-block');
        if (existing) existing.remove();

        if (data.ok || data.narrative) {
            p36RenderNarrative(data, scorecardData, card, btn);
            btn.textContent = '📝 Regenerate Narrative';
        } else {
            btn.textContent = '📝 Try again';
        }
        btn.disabled = false;

    } catch(e) {
        btn.textContent = '📝 Generate Narrative';
        btn.disabled = false;
    }
}

/* ---------------------------------------------------------
   36.3 — RENDER NARRATIVE BLOCK
--------------------------------------------------------- */
function p36RenderNarrative(data, scorecardData, card, btn) {
    const narrative   = data.narrative || data.narrative_text || '';
    const sentiment   = data.sentiment || 'positive';
    const recStrength = data.recommendation_strength || data.recommendation || '';
    const latency     = data.latency_ms || 0;
    const cost        = data.cost_usd || 0;

    // Drift detection vs scorecard
    const drift = p36ComputeDrift(data, scorecardData);

    const sentimentColor = {
        'positive':  '#00d68f',
        'neutral':   '#4d9fff',
        'mixed':     '#f5a623',
        'negative':  '#ff4d6d',
    }[sentiment] || '#4d9fff';

    const recColors = {
        'strong_yes': '#00d68f',
        'yes':        '#4d9fff',
        'maybe':      '#f5a623',
        'no':         '#ff4d6d',
    };
    const recColor = recColors[recStrength] || '#8ba4c0';
    const recLabel = {
        'strong_yes': 'Strong Hire',
        'yes':        'Hire',
        'maybe':      'Consider',
        'no':         'Pass',
    }[recStrength] || recStrength;

    const block = document.createElement('div');
    block.className = 'p36-narrative-block';
    block.id = `p36n_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    block.style.cssText = 'margin-top:12px;';

    // Expanded state
    let expanded = true;

    block.innerHTML = `
        <div style="padding:12px;border-radius:8px;background:rgba(29,110,245,0.06);border:1px solid rgba(29,110,245,0.15);">

            <!-- Header -->
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;opacity:0.55;">📝 AI Narrative</div>
                <div style="display:flex;align-items:center;gap:6px;">
                    ${recStrength ? `<span style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:999px;background:${recColor}22;color:${recColor};border:1px solid ${recColor}44;">${recLabel}</span>` : ''}
                    <span style="font-size:10px;padding:2px 7px;border-radius:999px;background:${sentimentColor}15;color:${sentimentColor};border:1px solid ${sentimentColor}33;">${sentiment}</span>
                </div>
            </div>

            <!-- Narrative text -->
            <div class="p36-narrative-text" style="font-size:12px;color:rgba(200,220,255,0.75);line-height:1.7;margin-bottom:10px;font-style:italic;">
                "${narrative}"
            </div>

            <!-- Drift warning if misaligned -->
            ${drift.show ? `
            <div style="padding:7px 10px;background:rgba(245,166,35,0.08);border:1px solid rgba(245,166,35,0.2);border-radius:6px;margin-bottom:8px;font-size:10px;color:#f5a623;">
                ⚠ ${drift.message}
            </div>` : ''}

            <!-- Footer actions -->
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                <button onclick="p36CopyNarrative(this)" style="font-size:10px;padding:3px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:transparent;cursor:pointer;color:inherit;">📋 Copy</button>
                <button onclick="p36ToggleNarrative(this)" style="font-size:10px;padding:3px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:transparent;cursor:pointer;color:inherit;">↑ Collapse</button>
                <button onclick="p36FeedbackNarrative('${data.narrative_id||''}','up',this)" style="font-size:10px;padding:3px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:transparent;cursor:pointer;color:inherit;">👍</button>
                <button onclick="p36FeedbackNarrative('${data.narrative_id||''}','down',this)" style="font-size:10px;padding:3px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:transparent;cursor:pointer;color:inherit;">👎</button>
                <span style="font-size:10px;opacity:0.35;margin-left:auto;">$${cost.toFixed(4)} · ${latency}ms</span>
            </div>
        </div>`;

    btn.insertAdjacentElement('afterend', block);
}

/* ---------------------------------------------------------
   36.4 — DRIFT DETECTION
   Compare narrative recommendation vs scorecard recommendation
--------------------------------------------------------- */
function p36ComputeDrift(narrativeData, scorecardData) {
    if (!scorecardData || !narrativeData.recommendation_strength) {
        return { show: false, message: '' };
    }

    const narRec   = narrativeData.recommendation_strength;
    const scoreRec = scorecardData.recommendation;

    // Map to numeric scale
    const scale = { strong_yes: 4, yes: 3, maybe: 2, no: 1 };
    const nVal  = scale[narRec]   || 2;
    const sVal  = scale[scoreRec] || 2;
    const diff  = Math.abs(nVal - sVal);

    if (diff >= 2) {
        return {
            show:    true,
            message: `Narrative (${narRec.replace('_',' ')}) vs Scorecard (${scoreRec.replace('_',' ')}) — significant drift detected. Review recommended.`,
        };
    } else if (diff === 1) {
        return {
            show:    true,
            message: `Minor variance between narrative and scorecard recommendation. Consider reviewing.`,
        };
    }
    return { show: false, message: '' };
}

/* ---------------------------------------------------------
   36.5 — TOGGLE EXPAND/COLLAPSE
--------------------------------------------------------- */
function p36ToggleNarrative(btn) {
    const block = btn.closest('.p36-narrative-block');
    if (!block) return;
    const text = block.querySelector('.p36-narrative-text');
    if (!text) return;
    const isVisible = text.style.display !== 'none';
    text.style.display = isVisible ? 'none' : 'block';
    btn.textContent = isVisible ? '↓ Expand' : '↑ Collapse';
}

/* ---------------------------------------------------------
   36.6 — COPY NARRATIVE
--------------------------------------------------------- */
function p36CopyNarrative(btn) {
    const block = btn.closest('.p36-narrative-block');
    if (!block) return;
    const text = block.querySelector('.p36-narrative-text');
    if (!text) return;
    const clean = text.textContent.replace(/[""]/g, '').trim();
    navigator.clipboard.writeText(clean).then(() => {
        btn.textContent = '✓ Copied';
        setTimeout(() => { btn.textContent = '📋 Copy'; }, 1800);
    });
}

/* ---------------------------------------------------------
   36.7 — FEEDBACK
--------------------------------------------------------- */
async function p36FeedbackNarrative(narrativeId, sentiment, btn) {
    try {
        await fetch('/api/narrative/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                narrative_id: narrativeId,
                feedback:     sentiment,
            })
        });
        btn.style.opacity = '1';
        btn.style.fontWeight = '700';
    } catch(e) {}
}

console.log('[Phase 36] Narrative Intelligence loaded ✓');