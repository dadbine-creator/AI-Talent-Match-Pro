/* ============================================================
   PHASE 35 — AI SCORECARDS
   Injects scorecard button into Phase 17 tier cards.
   Zero design changes — pure functionality layer.
   ============================================================ */

/* ---------------------------------------------------------
   35.1 — PATCH buildP17TierCard
   Adds "📊 Generate Scorecard" button after interview btn
--------------------------------------------------------- */
const _p35OriginalBuildCard = typeof buildP17TierCard === 'function' ? buildP17TierCard : null;

if (_p35OriginalBuildCard) {
    window.buildP17TierCard = function(candidate, tierKey) {
        const card = _p35OriginalBuildCard(candidate, tierKey);

        // Find last divider and inject after it
        const dividers = card.querySelectorAll('.p17-divider');
        const lastDivider = dividers[dividers.length - 1];

        if (lastDivider) {
            const divider = document.createElement('div');
            divider.className = 'p17-divider';

            const scorecardBtn = document.createElement('button');
            scorecardBtn.className = 'p17-read-more';
            scorecardBtn.setAttribute('aria-label', `Generate scorecard for ${candidate.name}`);
            scorecardBtn.textContent = '📊 Generate Scorecard';

            scorecardBtn.addEventListener('click', () => {
                p35GenerateScorecard(candidate, scorecardBtn, card);
            });

            lastDivider.insertAdjacentElement('afterend', divider);
            divider.insertAdjacentElement('afterend', scorecardBtn);
        }

        return card;
    };
}

/* ---------------------------------------------------------
   35.2 — GENERATE SCORECARD
--------------------------------------------------------- */
async function p35GenerateScorecard(candidate, btn, card) {
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

    btn.textContent = '⏳ Generating scorecard...';
    btn.disabled = true;

    try {
        const res = await fetch('/api/scorecard/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                candidate_id:       candidateId,
                candidate_name:     candidate.name,
                candidate_role:     candidate.role || '',
                candidate_tier:     candidate.tier || 'bronze',
                candidate_score:    candidate.score || 0,
                candidate_analysis: candidate.why || '',
                project_id:         localStorage.getItem('phase33_active_project') || null,
            })
        });
        const data = await res.json();

        // Remove existing scorecard block
        const existing = card.querySelector('.p35-scorecard-block');
        if (existing) existing.remove();

        const uid = data.scorecard_id || `temp_${Date.now()}`;
        data._uid = uid;
        if (data.ok) {
            p35RenderScorecard(data, card, btn);
            btn.textContent = '📊 Regenerate Scorecard';
        } else {
            btn.textContent = '📊 Try again';
        }
        btn.disabled = false;

    } catch(e) {
        btn.textContent = '📊 Generate Scorecard';
        btn.disabled = false;
    }
}

/* ---------------------------------------------------------
   35.3 — RENDER SCORECARD
--------------------------------------------------------- */
function p35RenderScorecard(data, card, btn) {
    const scorecard   = data.scorecard || {};
    const dimensions  = data.dimensions || scorecard.dimensions || [];
    const strengths   = data.strengths  || scorecard.strengths  || [];
    const concerns    = data.concerns   || scorecard.concerns   || [];
    const vsAI        = data.vs_ai_score || scorecard.vs_ai_score || {};
    const rec         = data.recommendation_label || scorecard.recommendation_label || 'Consider';
    const overall     = data.overall_score || scorecard.overall_score || 0;
    const summary     = data.summary || scorecard.summary || '';

    const recColors = {
        'Strong Hire': '#00d68f',
        'Hire':        '#4d9fff',
        'Consider':    '#f5a623',
        'Pass':        '#ff4d6d',
    };
    const recColor = recColors[rec] || '#8ba4c0';

    const block = document.createElement('div');
    block.className = 'p35-scorecard-block';
    block.id = `p35sc_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    block.style.cssText = 'margin-top:12px;';

    block.innerHTML = `
        <div style="padding:12px;border-radius:8px;background:rgba(29,110,245,0.06);border:1px solid rgba(29,110,245,0.15);">

            <!-- Header -->
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;opacity:0.55;">📊 AI Scorecard</div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-size:11px;font-weight:700;padding:3px 8px;border-radius:999px;background:${recColor}22;color:${recColor};border:1px solid ${recColor}44;">${rec}</span>
                    <span style="font-size:18px;font-weight:800;color:${recColor};">${overall.toFixed(1)}/10</span>
                </div>
            </div>

            <!-- Summary -->
            ${summary ? `<div style="font-size:11px;color:rgba(200,220,255,0.6);line-height:1.5;margin-bottom:10px;font-style:italic;">"${summary}"</div>` : ''}

            <!-- Dimensions -->
            <div style="display:flex;flex-direction:column;gap:5px;margin-bottom:10px;">
                ${dimensions.map(d => {
                    const flagColor = d.flag === 'strength' ? '#00d68f' : d.flag === 'concern' ? '#ff4d6d' : '#4d9fff';
                    const barWidth  = (d.score / 10) * 100;
                    return `
                    <div>
                        <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:2px;">
                            <span style="color:rgba(200,220,255,0.6);">${d.name}</span>
                            <span style="font-weight:700;color:${flagColor};">${d.score}/10</span>
                        </div>
                        <div style="height:3px;background:rgba(255,255,255,0.06);border-radius:999px;overflow:hidden;">
                            <div style="height:100%;width:${barWidth}%;background:${flagColor};border-radius:999px;transition:width 0.6s ease;"></div>
                        </div>
                    </div>`;
                }).join('')}
            </div>

            <!-- Strengths + Concerns -->
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">
                <div style="padding:8px;background:rgba(0,214,143,0.05);border:1px solid rgba(0,214,143,0.12);border-radius:6px;">
                    <div style="font-size:9px;font-weight:700;color:#00d68f;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:5px;">Strengths</div>
                    ${strengths.map(s => `<div style="font-size:10px;color:rgba(200,220,255,0.6);margin-bottom:2px;">✓ ${s}</div>`).join('')}
                </div>
                <div style="padding:8px;background:rgba(255,77,109,0.05);border:1px solid rgba(255,77,109,0.12);border-radius:6px;">
                    <div style="font-size:9px;font-weight:700;color:#ff4d6d;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:5px;">Watch</div>
                    ${concerns.map(c => `<div style="font-size:10px;color:rgba(200,220,255,0.6);margin-bottom:2px;">⚠ ${c}</div>`).join('')}
                </div>
            </div>

            <!-- VS AI Score -->
            ${vsAI.ai_score ? `
            <div style="padding:8px;background:rgba(255,255,255,0.03);border-radius:6px;font-size:10px;color:rgba(200,220,255,0.5);margin-bottom:10px;">
                <span style="font-weight:700;color:rgba(200,220,255,0.8);">AI Score:</span> ${vsAI.ai_score}% &nbsp;·&nbsp;
                <span style="font-weight:700;color:rgba(200,220,255,0.8);">Scorecard:</span> ${(overall * 10).toFixed(0)}% &nbsp;·&nbsp;
                <span style="color:rgba(200,220,255,0.4);">${vsAI.alignment || 'aligned'}</span>
            </div>` : ''}

            <!-- Human Score Section -->
            <div style="border-top:1px solid rgba(255,255,255,0.06);padding-top:8px;">
                <div style="font-size:9px;font-weight:700;color:rgba(150,180,220,0.5);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">Your Score</div>
                <div style="display:flex;align-items:center;gap:6px;">
                    <input type="range" min="1" max="10" value="7" id="humanScore_${data.scorecard_id||'x'}"
                        style="flex:1;accent-color:#4d9fff;"
                        oninput="document.getElementById('humanScoreVal_${data.scorecard_id||'x'}').textContent=this.value"/>
                    <span id="humanScoreVal_${data.scorecard_id||'x'}" style="font-size:13px;font-weight:700;color:#4d9fff;width:20px;">7</span>
                    <button onclick="p35SubmitHumanScore('${data.scorecard_id||''}',this)"
                        style="font-size:10px;padding:4px 10px;border-radius:6px;border:1px solid rgba(29,110,245,0.25);background:rgba(29,110,245,0.1);color:#4d9fff;cursor:pointer;">
                        Submit
                    </button>
                </div>
            </div>

            <!-- Footer -->
            <div style="display:flex;gap:6px;margin-top:8px;">
                <button onclick="p35CopyScorecard(this)" style="font-size:10px;padding:3px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:transparent;cursor:pointer;color:inherit;">📋 Copy</button>
                <span style="font-size:10px;opacity:0.35;margin-left:auto;">$${(data.cost_usd||0).toFixed(4)} · ${data.latency_ms||0}ms</span>
            </div>
        </div>`;

    btn.insertAdjacentElement('afterend', block);
}

/* ---------------------------------------------------------
   35.4 — SUBMIT HUMAN SCORE
--------------------------------------------------------- */
async function p35SubmitHumanScore(scorecardId, btn) {
    if (!scorecardId) return;
    const slider = document.getElementById(`humanScore_${scorecardId}`);
    const score  = slider ? parseInt(slider.value) : 7;

    try {
        await fetch(`/api/scorecard/${scorecardId}/human-score`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scores: { overall: score } })
        });
        btn.textContent = '✓ Scored';
        btn.style.color = '#00d68f';
    } catch(e) {
        btn.textContent = '✓ Scored';
        btn.style.color = '#00d68f';
    }
}

/* ---------------------------------------------------------
   35.5 — COPY SCORECARD
--------------------------------------------------------- */
function p35CopyScorecard(btn) {
    const block = btn.closest('.p35-scorecard-block');
    if (!block) return;
    const text = block.innerText.replace(/📊|✓|⚠|📋/g, '').trim();
    navigator.clipboard.writeText(text).then(() => {
        btn.textContent = '✓ Copied';
        setTimeout(() => { btn.textContent = '📋 Copy'; }, 1800);
    });
}

console.log('[Phase 35] AI Scorecards loaded ✓');