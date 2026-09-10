/* ============================================================
   PHASE 34 — AI INTERVIEW QUESTIONS
   Injects "Generate Interview Questions" button into
   existing Phase 17 tier cards. Zero design changes.
   ============================================================ */

/* ---------------------------------------------------------
   34.1 — PATCH buildP17TierCard
   Adds interview questions button after outreach button
--------------------------------------------------------- */
const _p34OriginalBuildCard = typeof buildP17TierCard === 'function' ? buildP17TierCard : null;

if (_p34OriginalBuildCard) {
    window.buildP17TierCard = function(candidate, tierKey) {
        const card = _p34OriginalBuildCard(candidate, tierKey);

        // Find the last p17-divider and add after it
        const dividers = card.querySelectorAll('.p17-divider');
        const lastDivider = dividers[dividers.length - 1];

        if (lastDivider) {
            const divider = document.createElement('div');
            divider.className = 'p17-divider';

            const interviewBtn = document.createElement('button');
            interviewBtn.className = 'p17-read-more';
            interviewBtn.setAttribute('aria-label', `Generate interview questions for ${candidate.name}`);
            interviewBtn.textContent = '🎯 Generate Interview Questions';

            interviewBtn.addEventListener('click', () => {
                p34GenerateQuestions(candidate, interviewBtn, card);
            });

            lastDivider.insertAdjacentElement('afterend', divider);
            divider.insertAdjacentElement('afterend', interviewBtn);
        }

        return card;
    };
}

/* ---------------------------------------------------------
   34.2 — GENERATE INTERVIEW QUESTIONS
--------------------------------------------------------- */
async function p34GenerateQuestions(candidate, btn, card) {
    if (!btn || !card) return;

    // Find candidate ID
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

    btn.textContent = '⏳ Generating questions...';
    btn.disabled = true;

    try {
        const res = await fetch('/api/interview/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                candidate_id: candidateId,
                candidate_name: candidate.name,
                candidate_role: candidate.role || '',
                candidate_tier: candidate.tier || 'bronze',
                candidate_score: candidate.score || 0,
                candidate_analysis: candidate.why || '',
                project_id: localStorage.getItem('phase33_active_project') || null
            })
        });
        const data = await res.json();

        // Remove existing block if any
        const existing = card.querySelector('.p34-questions-block');
        if (existing) existing.remove();

        if (data.ok && data.questions?.length) {
            p34RenderQuestions(data.questions, data, card, btn);
            btn.textContent = '🎯 Regenerate Questions';
        } else {
            btn.textContent = '🎯 Try again';
        }
        btn.disabled = false;

    } catch(e) {
        btn.textContent = '🎯 Generate Interview Questions';
        btn.disabled = false;
    }
}

/* ---------------------------------------------------------
   34.3 — RENDER QUESTIONS INTO CARD
--------------------------------------------------------- */
function p34RenderQuestions(questions, meta, card, btn) {
    const block = document.createElement('div');
    block.className = 'p34-questions-block';
    block.id = `p34q_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    block.style.cssText = 'margin-top:12px;';

    // Header
    const header = document.createElement('div');
    header.style.cssText = 'font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;opacity:0.55;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between;';
    header.innerHTML = `
        <span>🎯 Interview Questions · ${questions.length} generated</span>
        <span style="opacity:0.5;">${meta.tier?.toUpperCase() || ''} · $${(meta.cost_usd||0).toFixed(4)}</span>
    `;
    block.appendChild(header);

    // Category filter tabs
    const categories = [...new Set(questions.map(q => q.category))];
    const tabBar = document.createElement('div');
    tabBar.style.cssText = 'display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px;';
    tabBar.innerHTML = `<button onclick="p34FilterQuestions(this,'all','${block.id || ''}')" style="${p34TabStyle(true)}">All</button>` +
        categories.map(cat => `<button onclick="p34FilterQuestions(this,'${cat}','${block.id || ''}')" style="${p34TabStyle(false)}">${cat}</button>`).join('');
    block.appendChild(tabBar);

    // Questions list
    const list = document.createElement('div');
    list.className = 'p34-question-list';

    questions.forEach((q, i) => {
        const item = document.createElement('div');
        item.className = 'p34-question-item';
        item.dataset.category = q.category;
        item.style.cssText = `
            padding:10px 12px;
            border-radius:8px;
            background:rgba(29,110,245,0.06);
            border:1px solid rgba(29,110,245,0.14);
            margin-bottom:7px;
            font-size:12px;
            line-height:1.55;
        `;

        const diffColor = {
            'Starter':    'rgba(0,214,143,0.7)',
            'Core':       'rgba(77,159,255,0.8)',
            'Deep Dive':  'rgba(245,166,35,0.8)',
            'Challenge':  'rgba(255,77,109,0.8)',
        }[q.difficulty] || 'rgba(150,180,220,0.5)';

        item.innerHTML = `
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap;">
                <span style="font-size:9px;font-weight:700;padding:2px 6px;border-radius:999px;background:${diffColor};color:white;">${q.difficulty}</span>
                <span style="font-size:9px;opacity:0.5;">${q.category}</span>
                <span style="margin-left:auto;font-size:10px;opacity:0.4;">${i+1}/${questions.length}</span>
            </div>
            <div style="font-weight:600;margin-bottom:6px;color:inherit;">${q.question}</div>
            <div class="p34-detail" style="display:none;">
                <div style="margin-top:6px;padding:8px;border-radius:6px;background:rgba(0,0,0,0.15);">
                    <div style="font-size:10px;opacity:0.5;margin-bottom:3px;">WHY ASK THIS</div>
                    <div style="font-size:11px;opacity:0.7;">${q.why || ''}</div>
                </div>
                <div style="margin-top:6px;padding:8px;border-radius:6px;background:rgba(0,214,143,0.06);">
                    <div style="font-size:10px;opacity:0.5;margin-bottom:3px;">WHAT GOOD LOOKS LIKE</div>
                    <div style="font-size:11px;opacity:0.7;">${q.what_good_looks_like || ''}</div>
                </div>
                <div style="margin-top:6px;padding:8px;border-radius:6px;background:rgba(255,255,255,0.04);">
                    <div style="font-size:10px;opacity:0.5;margin-bottom:3px;">FOLLOW-UP</div>
                    <div style="font-size:11px;opacity:0.7;">${q.follow_up || ''}</div>
                </div>
            </div>
            <button onclick="p34ToggleDetail(this)" style="font-size:10px;margin-top:5px;padding:2px 8px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:transparent;cursor:pointer;color:inherit;opacity:0.6;">
                Show detail ↓
            </button>
        `;

        list.appendChild(item);
    });

    block.appendChild(list);

    // Footer actions
    const footer = document.createElement('div');
    footer.style.cssText = 'display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;';
    footer.innerHTML = `
        <button onclick="p34CopyAll(this)" style="font-size:11px;padding:4px 10px;border-radius:6px;border:1px solid rgba(255,255,255,0.12);background:transparent;cursor:pointer;color:inherit;">
            📋 Copy all
        </button>
        <button onclick="p34MarkUsed('${meta.set_id||''}', this)" style="font-size:11px;padding:4px 10px;border-radius:6px;border:1px solid rgba(255,255,255,0.12);background:transparent;cursor:pointer;color:inherit;">
            ✓ Mark as used
        </button>
    `;
    block.appendChild(footer);

    // Insert after button
    btn.insertAdjacentElement('afterend', block);
}

/* ---------------------------------------------------------
   34.4 — HELPER: TAB STYLE
--------------------------------------------------------- */
function p34TabStyle(active) {
    return `font-size:10px;padding:2px 8px;border-radius:999px;border:1px solid rgba(255,255,255,${active?'0.2':'0.08'});background:${active?'rgba(29,110,245,0.15)':'transparent'};cursor:pointer;color:inherit;opacity:${active?'1':'0.55'};`;
}

/* ---------------------------------------------------------
   34.5 — FILTER QUESTIONS BY CATEGORY
--------------------------------------------------------- */
function p34FilterQuestions(tabBtn, category) {
    // Update tab styles
    const tabs = tabBtn.parentElement.querySelectorAll('button');
    tabs.forEach(t => {
        t.style.cssText = p34TabStyle(false);
    });
    tabBtn.style.cssText = p34TabStyle(true);

    // Filter items
    const block = tabBtn.closest('.p34-questions-block');
    if (!block) return;
    block.querySelectorAll('.p34-question-item').forEach(item => {
        item.style.display = (category === 'all' || item.dataset.category.toLowerCase() === category.toLowerCase()) ? 'block' : 'none';
    });
}

/* ---------------------------------------------------------
   34.6 — TOGGLE QUESTION DETAIL
--------------------------------------------------------- */
function p34ToggleDetail(btn) {
    const detail = btn.previousElementSibling;
    if (!detail || !detail.classList.contains('p34-detail')) return;
    const isOpen = detail.style.display !== 'none';
    detail.style.display = isOpen ? 'none' : 'block';
    btn.textContent = isOpen ? 'Show detail ↓' : 'Hide detail ↑';
}

/* ---------------------------------------------------------
   34.7 — COPY ALL QUESTIONS TO CLIPBOARD
--------------------------------------------------------- */
function p34CopyAll(btn) {
    const block = btn.closest('.p34-questions-block');
    if (!block) return;

    const items = block.querySelectorAll('.p34-question-item');
    const text = Array.from(items).map((item, i) => {
        const q = item.querySelector('div[style*="font-weight:600"]')?.textContent || '';
        const diff = item.querySelector('span[style*="border-radius:999px"]')?.textContent || '';
        const cat = item.querySelectorAll('span')[1]?.textContent || '';
        return `${i+1}. [${diff} | ${cat}]\n${q}`;
    }).join('\n\n');

    navigator.clipboard.writeText(text).then(() => {
        btn.textContent = '✓ Copied!';
        setTimeout(() => { btn.textContent = '📋 Copy all'; }, 1800);
    }).catch(() => {
        btn.textContent = '📋 Copy all';
    });
}

/* ---------------------------------------------------------
   34.8 — MARK QUESTION SET AS USED IN INTERVIEW
--------------------------------------------------------- */
async function p34MarkUsed(setId, btn) {
    if (!setId) return;
    try {
        await fetch(`/api/interview/${setId}/used`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ used: true })
        });
        if (btn) { btn.textContent = '✓ Used'; btn.style.color = '#00d68f'; }
    } catch(e) {}
}

/* ---------------------------------------------------------
   34.9 — INIT (silent)
--------------------------------------------------------- */
console.log('[Phase 34] AI Interview Questions loaded ✓');