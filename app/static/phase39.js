/* ============================================================
   PHASE 39 — AI RECRUITER COACHING + SSO
   Real-time coaching · Coaching score · Apply tips
   ============================================================ */

console.log('[Phase 39] AI Recruiter Coaching loaded ✓');

document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('p39CoachingList')) {
        p39LoadCoaching();
        p39UpdateCoachingScore();
    }
});

/* ---------------------------------------------------------
   39.1 — LOAD COACHING EVENTS
--------------------------------------------------------- */
async function p39LoadCoaching() {
    const el = document.getElementById('p39CoachingList');
    if (!el) return;

    try {
        const res  = await fetch('/api/coaching/recent');
        const data = await res.json();
        const events = data.events || [];

        if (!events.length) {
            el.innerHTML = `
            <div style="text-align:center;padding:20px;color:var(--text-muted);font-size:12px;">
                No coaching insights yet —
                <button onclick="p39GenerateCoaching()" style="color:#4d9fff;background:transparent;border:none;cursor:pointer;font-size:12px;">analyze my behavior</button>
            </div>`;
            return;
        }

        el.innerHTML = events.map(e => p39RenderCoachingItem(e)).join('');
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Coaching unavailable</div>';
    }
}

/* ---------------------------------------------------------
   39.2 — RENDER COACHING ITEM
--------------------------------------------------------- */
function p39RenderCoachingItem(event) {
    return `
    <div id="coaching_${event.id}" style="padding:12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-left:3px solid ${event.severity_color};border-radius:8px;margin-bottom:8px;">
        <div style="display:flex;align-items:flex-start;gap:10px;">
            <div style="font-size:18px;flex-shrink:0;">${event.icon}</div>
            <div style="flex:1;">
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                    <span style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:${event.severity_color};">${event.label}</span>
                    <span style="font-size:10px;color:var(--text-muted);">${event.time_ago}</span>
                    ${event.is_applied ? '<span style="font-size:10px;color:#00d68f;">✓ Applied</span>' : ''}
                </div>
                <div style="font-size:12px;color:rgba(200,220,255,0.75);line-height:1.6;">${event.message}</div>
                <div style="display:flex;gap:6px;margin-top:8px;">
                    ${!event.is_applied ? `<button onclick="p39ApplyTip('${event.id}',this)" style="font-size:11px;padding:4px 10px;border-radius:6px;border:1px solid rgba(0,214,143,0.3);background:rgba(0,214,143,0.08);color:#00d68f;cursor:pointer;">✓ Apply Tip</button>` : ''}
                    ${!event.is_read ? `<button onclick="p39MarkRead('${event.id}',this)" style="font-size:11px;padding:4px 10px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:transparent;color:var(--text-muted);cursor:pointer;">Mark Read</button>` : ''}
                </div>
            </div>
        </div>
    </div>`;
}

/* ---------------------------------------------------------
   39.3 — GENERATE COACHING
--------------------------------------------------------- */
async function p39GenerateCoaching() {
    const el  = document.getElementById('p39CoachingList');
    const btn = event?.target;
    if (btn) btn.textContent = 'Analyzing...';

    try {
        const res  = await fetch('/api/coaching/generate', { method: 'POST' });
        const data = await res.json();
        if (data.ok) {
            p39LoadCoaching();
            p39UpdateCoachingScore();
        }
    } catch(e) {}
    if (btn) btn.textContent = 'analyze my behavior';
}

/* ---------------------------------------------------------
   39.4 — APPLY TIP
--------------------------------------------------------- */
async function p39ApplyTip(eventId, btn) {
    try {
        await fetch(`/api/coaching/${eventId}/applied`, { method: 'PATCH' });
        const card = document.getElementById(`coaching_${eventId}`);
        if (card) {
            card.style.borderLeftColor = '#00d68f';
            card.style.opacity = '0.7';
        }
        if (btn) { btn.textContent = '✓ Applied'; btn.style.color = '#00d68f'; btn.disabled = true; }
        p39UpdateCoachingScore();
    } catch(e) {}
}

/* ---------------------------------------------------------
   39.5 — MARK READ
--------------------------------------------------------- */
async function p39MarkRead(eventId, btn) {
    try {
        await fetch('/api/coaching/mark-read', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event_ids: [eventId] })
        });
        if (btn) btn.remove();
    } catch(e) {}
}

/* ---------------------------------------------------------
   39.6 — COACHING SCORE
--------------------------------------------------------- */
async function p39UpdateCoachingScore() {
    try {
        const res  = await fetch('/api/coaching/score');
        const data = await res.json();

        const scoreEl = document.getElementById('p39CoachingScore');
        const gradeEl = document.getElementById('p39CoachingGrade');
        if (scoreEl) scoreEl.textContent = data.overall || '—';
        if (gradeEl) {
            const colors = { A: '#00d68f', B: '#4d9fff', C: '#f5a623', D: '#ff4d6d' };
            gradeEl.textContent  = data.grade || '—';
            gradeEl.style.color  = colors[data.grade] || '#8ba4c0';
        }

        // Update breakdown
        const breakdown = document.getElementById('p39CoachingBreakdown');
        if (breakdown && data.scores) {
            const labels = {
                outreach_quality:       'Outreach Quality',
                signal_responsiveness:  'Signal Response',
                pipeline_management:    'Pipeline Mgmt',
                copilot_usage:          'Copilot Usage',
            };
            breakdown.innerHTML = Object.entries(data.scores).map(([k, v]) => `
            <div style="margin-bottom:6px;">
                <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:2px;">
                    <span style="color:var(--text-muted);">${labels[k] || k}</span>
                    <span style="color:#4d9fff;font-weight:700;">${v}</span>
                </div>
                <div style="height:4px;background:rgba(255,255,255,0.06);border-radius:999px;overflow:hidden;">
                    <div style="height:100%;width:${v}%;background:${v >= 70 ? '#00d68f' : v >= 50 ? '#4d9fff' : '#f5a623'};border-radius:999px;transition:width 0.8s;"></div>
                </div>
            </div>`).join('');
        }
    } catch(e) {}
}