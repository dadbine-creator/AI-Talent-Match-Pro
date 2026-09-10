/* ============================================================
   PHASE 38 — REAL-TIME CANDIDATE SIGNALS
   Live signal stream · Signal badges on tier cards
   Polling every 5s (looks real-time, zero WebSocket risk)
   ============================================================ */

console.log('[Phase 38] Real-Time Candidate Signals loaded ✓');

// ── Polling state ─────────────────────────────────────────
let _p38PollInterval  = null;
let _p38LastSignalId  = null;
let _p38SignalCount   = 0;

// ── Auto-start polling when workspace loads ───────────────
document.addEventListener('DOMContentLoaded', () => {
    p38StartPolling();
    if (document.getElementById('p38SignalStream')) {
        p38LoadSignalStream();
        p38LoadSummary();
    }
});

/* ---------------------------------------------------------
   38.1 — POLLING (5s interval, looks real-time)
--------------------------------------------------------- */
function p38StartPolling() {
    if (_p38PollInterval) return;
    _p38PollInterval = setInterval(p38Poll, 5000);
    p38Poll(); // immediate first call
}

function p38StopPolling() {
    if (_p38PollInterval) {
        clearInterval(_p38PollInterval);
        _p38PollInterval = null;
    }
}

async function p38Poll() {
    try {
        const res  = await fetch('/api/signals/recent?limit=5');
        const data = await res.json();
        if (!data.ok || !data.signals?.length) return;

        const latest = data.signals[0];
        if (latest.id === _p38LastSignalId) return; // no new signals

        _p38LastSignalId = latest.id;

        // New signals! Update UI
        p38HandleNewSignals(data.signals);
        p38UpdateBadgeCount(data.total);

    } catch(e) { /* silent fail — polling will retry */ }
}

/* ---------------------------------------------------------
   38.2 — HANDLE NEW SIGNALS
--------------------------------------------------------- */
function p38HandleNewSignals(signals) {
    // Update live signal container in workspace (if visible)
    const container = document.getElementById('liveSignalsContainer');
    if (container) {
        signals.slice(0, 5).forEach(s => {
            const existing = document.getElementById(`signal_${s.id}`);
            if (!existing) {
                p38PrependSignalItem(container, s);
            }
        });
    }

    // Update candidate cards with badges
    signals.forEach(s => {
        if (s.candidate_id) {
            p38UpdateCandidateCard(s);
        }
    });

    // Show toast for high-priority signals
    const high = signals.find(s => ['open_to_work', 'recruiter_message_replied', 'job_change', 'interest_spike'].includes(s.signal_type));
    if (high) {
        p38ShowSignalToast(high);
    }
}

/* ---------------------------------------------------------
   38.3 — SIGNAL ITEM RENDERER
--------------------------------------------------------- */
function p38PrependSignalItem(container, signal) {
    const item = document.createElement('div');
    item.id = `signal_${signal.id}`;
    item.className = 'p38-signal-item';
    item.style.cssText = `
        display:flex;align-items:flex-start;gap:10px;
        padding:8px;background:rgba(255,255,255,0.02);
        border:1px solid rgba(255,255,255,0.06);
        border-left:3px solid ${signal.badge_color};
        border-radius:8px;margin-bottom:6px;
        animation:p38FadeIn 0.3s ease;
    `;
    item.innerHTML = `
        <div style="font-size:18px;flex-shrink:0;">${signal.icon}</div>
        <div style="flex:1;min-width:0;">
            <div style="font-size:12px;font-weight:600;color:var(--text);">${signal.label}</div>
            <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${signal.time_ago}</div>
        </div>
        <div style="font-size:10px;padding:2px 6px;border-radius:999px;background:${signal.badge_color}22;color:${signal.badge_color};border:1px solid ${signal.badge_color}44;flex-shrink:0;">
            ${Math.round(signal.confidence_score * 100)}%
        </div>`;

    // Prepend with max 20 items
    container.insertBefore(item, container.firstChild);
    const items = container.querySelectorAll('.p38-signal-item');
    if (items.length > 20) items[items.length - 1].remove();
}

/* ---------------------------------------------------------
   38.4 — SIGNAL BADGES ON TIER CARDS
--------------------------------------------------------- */
function p38UpdateCandidateCard(signal) {
    // Find tier cards matching this candidate
    const cards = document.querySelectorAll('.p17-tier-card, .candidate-card, [data-candidate-id]');
    cards.forEach(card => {
        const nameEl = card.querySelector('.p17-name, .candidate-name, [data-name]');
        if (!nameEl) return;

        // Inject badge
        const badgeId = `badge_${signal.candidate_id}_${signal.signal_type}`;
        if (document.getElementById(badgeId)) return; // already shown

        const badge = document.createElement('span');
        badge.id = badgeId;
        badge.style.cssText = `
            display:inline-flex;align-items:center;gap:3px;
            font-size:9px;font-weight:700;
            padding:2px 6px;border-radius:999px;
            background:${signal.badge_color}22;
            color:${signal.badge_color};
            border:1px solid ${signal.badge_color}44;
            margin-left:6px;
            animation:p38FadeIn 0.3s ease;
        `;
        badge.textContent = `${signal.icon} ${signal.label}`;
        nameEl.insertAdjacentElement('afterend', badge);

        // Auto-remove after 30s
        setTimeout(() => badge.remove(), 30000);
    });
}

/* ---------------------------------------------------------
   38.5 — SIGNAL TOAST NOTIFICATION
--------------------------------------------------------- */
function p38ShowSignalToast(signal) {
    const toast = document.createElement('div');
    toast.style.cssText = `
        position:fixed;bottom:24px;right:24px;z-index:9999;
        background:#0d1829;border:1px solid ${signal.badge_color};
        border-radius:12px;padding:14px 18px;
        display:flex;align-items:center;gap:12px;
        box-shadow:0 8px 32px rgba(0,0,0,0.4);
        animation:p38SlideIn 0.3s ease;
        max-width:320px;
    `;
    toast.innerHTML = `
        <div style="font-size:22px;">${signal.icon}</div>
        <div>
            <div style="font-size:13px;font-weight:700;color:#fff;">${signal.label}</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.5);margin-top:2px;">${signal.time_ago}</div>
        </div>
        <button onclick="this.parentElement.remove()" style="background:transparent;border:none;color:rgba(255,255,255,0.3);cursor:pointer;font-size:16px;margin-left:auto;">×</button>
    `;
    document.body.appendChild(toast);
    setTimeout(() => { if (toast.parentElement) toast.remove(); }, 5000);
}

/* ---------------------------------------------------------
   38.6 — BADGE COUNTER
--------------------------------------------------------- */
function p38UpdateBadgeCount(total) {
    _p38SignalCount = total;
    const counter = document.getElementById('p38SignalCount');
    if (counter) {
        counter.textContent = total > 0 ? total : '';
        counter.style.display = total > 0 ? 'inline' : 'none';
    }
}

/* ---------------------------------------------------------
   38.7 — ANALYTICS: SIGNAL STREAM
--------------------------------------------------------- */
async function p38LoadSignalStream() {
    const el = document.getElementById('p38SignalStream');
    if (!el) return;

    try {
        const res  = await fetch('/api/signals/recent?limit=20');
        const data = await res.json();
        const signals = data.signals || [];

        if (!signals.length) {
            el.innerHTML = `
                <div style="text-align:center;padding:20px;color:var(--text-muted);font-size:12px;">
                    No signals yet —
                    <button onclick="p38SimulateSignals()" style="color:#4d9fff;background:transparent;border:none;cursor:pointer;font-size:12px;">generate demo signals</button>
                </div>`;
            return;
        }

        el.innerHTML = signals.map(s => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-left:3px solid ${s.badge_color};border-radius:8px;margin-bottom:6px;">
            <div style="font-size:16px;">${s.icon}</div>
            <div style="flex:1;">
                <div style="font-size:12px;font-weight:600;color:var(--text);">${s.label}</div>
                <div style="font-size:10px;color:var(--text-muted);">${s.time_ago}</div>
            </div>
            <div style="font-size:10px;padding:2px 6px;border-radius:999px;background:${s.badge_color}15;color:${s.badge_color};">${Math.round(s.confidence_score*100)}%</div>
        </div>`).join('');
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Signal stream unavailable</div>';
    }
}

/* ---------------------------------------------------------
   38.8 — ANALYTICS: SIGNAL SUMMARY
--------------------------------------------------------- */
async function p38LoadSummary() {
    try {
        const res  = await fetch('/api/signals/summary');
        const data = await res.json();

        const setEl = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val;
        };

        setEl('p38TotalSignals',    data.total_signals || 0);
        setEl('p38InterestSpikes',  (data.interest_spikes || []).length);
        setEl('p38RiskSignals',     (data.risk_signals || []).length);
        setEl('p38SkillUpdates',    (data.skill_updates || []).length);
        setEl('p38JobChanges',      (data.job_changes || []).length);
        setEl('p38OpenToWork',      (data.open_to_work || []).length);

    } catch(e) {}
}

/* ---------------------------------------------------------
   38.9 — SIMULATE DEMO SIGNALS
--------------------------------------------------------- */
async function p38SimulateSignals() {
    try {
        const res  = await fetch('/api/signals/simulate', { method: 'POST' });
        const data = await res.json();
        if (data.ok) {
            p38LoadSignalStream();
            p38LoadSummary();
        }
    } catch(e) {}
}

/* ---------------------------------------------------------
   38.10 — CSS ANIMATIONS
--------------------------------------------------------- */
const p38Style = document.createElement('style');
p38Style.textContent = `
@keyframes p38FadeIn {
    from { opacity: 0; transform: translateY(-8px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes p38SlideIn {
    from { opacity: 0; transform: translateX(20px); }
    to   { opacity: 1; transform: translateX(0); }
}
`;
document.head.appendChild(p38Style);