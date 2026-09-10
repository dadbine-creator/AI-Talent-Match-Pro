/* ============================================================
   PHASE 42 — GLOBAL ROLLOUT MODE
   Feature Flags · AI Model Router · Status Page
   LinkedIn OAuth · API v2 · Data Residency
   ============================================================ */

console.log('[Phase 42] Global Rollout Mode loaded ✓');

document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('p42FeatureFlags'))  p42LoadFeatureFlags();
    if (document.getElementById('p42AIRouter'))      p42LoadAIRouter();
    if (document.getElementById('p42StatusPage'))    p42LoadStatusPage();
    if (document.getElementById('p42DataResidency')) p42LoadDataResidency();
    if (document.getElementById('p42Regions'))       p42LoadRegions();
});

/* ---------------------------------------------------------
   42.1 — FEATURE FLAGS
--------------------------------------------------------- */
async function p42LoadFeatureFlags() {
    const el = document.getElementById('p42FeatureFlags');
    if (!el) return;

    try {
        const res  = await fetch('/api/flags');
        const data = await res.json();
        const flags = data.flags || [];

        el.innerHTML = flags.map(f => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:8px;margin-bottom:6px;">
            <div style="flex:1;">
                <div style="font-size:12px;font-weight:600;color:var(--text);">${f.key}</div>
                <div style="font-size:10px;color:var(--text-muted);">${f.description}</div>
            </div>
            <div style="font-size:10px;color:var(--text-muted);margin-right:6px;">${f.rollout_pct}%</div>
            <div onclick="p42ToggleFlag('${f.key}', ${!f.enabled})"
                style="width:36px;height:20px;border-radius:999px;background:${f.enabled ? '#00d68f' : 'rgba(255,255,255,0.1)'};cursor:pointer;transition:background 0.2s;position:relative;">
                <div style="position:absolute;top:2px;${f.enabled ? 'right:2px' : 'left:2px'};width:16px;height:16px;border-radius:50%;background:#fff;transition:all 0.2s;"></div>
            </div>
        </div>`).join('');
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Feature flags unavailable</div>';
    }
}

async function p42ToggleFlag(flagKey, enabled) {
    try {
        await fetch(`/api/flags/${flagKey}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });
        p42LoadFeatureFlags();
    } catch(e) {}
}

/* ---------------------------------------------------------
   42.2 — AI MODEL ROUTER
--------------------------------------------------------- */
async function p42LoadAIRouter() {
    const el = document.getElementById('p42AIRouter');
    if (!el) return;

    try {
        const res  = await fetch('/api/ai/models');
        const data = await res.json();
        const models = data.models || {};

        el.innerHTML = Object.entries(models).map(([key, m]) => `
        <div style="padding:12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;margin-bottom:8px;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
                <div style="font-size:13px;font-weight:700;color:var(--text);">${m.label}</div>
                <span style="font-size:10px;padding:2px 7px;border-radius:999px;background:rgba(0,214,143,0.1);color:#00d68f;border:1px solid rgba(0,214,143,0.2);">${m.status || 'active'}</span>
            </div>
            <div style="display:flex;gap:12px;font-size:11px;color:var(--text-muted);">
                <span>⚡ ${m.latency_ms}ms</span>
                <span>💰 $${m.cost_per_1k}/1k tokens</span>
                <span>🌍 ${m.region}</span>
            </div>
            <div style="margin-top:6px;font-size:10px;color:rgba(200,220,255,0.4);">Best for: ${(m.best_for || []).join(', ')}</div>
        </div>`).join('');
    } catch(e) {}
}

async function p42RouteTest() {
    const action = document.getElementById('p42RouteAction')?.value || 'scoring';
    const tier   = document.getElementById('p42RouteTier')?.value || 'business';
    const el     = document.getElementById('p42RouteResult');

    try {
        const res  = await fetch(`/api/ai/route?action=${action}&tier=${tier}`);
        const data = await res.json();
        if (el) el.innerHTML = `
        <div style="padding:10px;background:rgba(0,214,143,0.05);border:1px solid rgba(0,214,143,0.15);border-radius:8px;font-size:12px;">
            <div style="color:#00d68f;font-weight:700;margin-bottom:4px;">→ ${data.model}</div>
            <div style="color:var(--text-muted);">${data.reason}</div>
            <div style="color:var(--text-muted);margin-top:4px;">⚡ ${data.latency_ms}ms · Fallback: ${data.fallback_model}</div>
        </div>`;
    } catch(e) {}
}

/* ---------------------------------------------------------
   42.3 — STATUS PAGE
--------------------------------------------------------- */
async function p42LoadStatusPage() {
    const el = document.getElementById('p42StatusPage');
    if (!el) return;

    try {
        const res  = await fetch('/api/status');
        const data = await res.json();

        const overallBg = data.overall === 'operational'
            ? 'rgba(0,214,143,0.08)' : 'rgba(245,166,35,0.08)';

        el.innerHTML = `
        <div style="padding:12px;background:${overallBg};border:1px solid ${data.overall_color}33;border-radius:8px;margin-bottom:12px;display:flex;align-items:center;gap:10px;">
            <div style="width:10px;height:10px;border-radius:50%;background:${data.overall_color};animation:blink 2s infinite;"></div>
            <div style="font-size:13px;font-weight:700;color:${data.overall_color};">All Systems ${data.overall === 'operational' ? 'Operational' : 'Degraded'}</div>
            <div style="margin-left:auto;font-size:11px;color:var(--text-muted);">30d uptime: ${data.uptime_30d}%</div>
        </div>
        ${data.components.map(c => `
        <div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04);">
            <div style="width:8px;height:8px;border-radius:50%;background:${c.color};flex-shrink:0;"></div>
            <div style="flex:1;font-size:12px;color:var(--text-soft);">${c.name}</div>
            <div style="font-size:10px;color:${c.color};">${c.status}</div>
        </div>`).join('')}
        ${data.incidents.length ? `
        <div style="margin-top:12px;">
            <div style="font-size:11px;font-weight:700;color:#f5a623;margin-bottom:6px;">Active Incidents</div>
            ${data.incidents.map(i => `
            <div style="padding:8px;background:rgba(245,166,35,0.05);border:1px solid rgba(245,166,35,0.15);border-radius:6px;margin-bottom:4px;">
                <div style="font-size:12px;font-weight:600;color:var(--text);">${i.title}</div>
                <div style="font-size:11px;color:var(--text-muted);">${i.message}</div>
            </div>`).join('')}
        </div>` : ''}`;
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Status unavailable</div>';
    }
}

/* ---------------------------------------------------------
   42.4 — DATA RESIDENCY
--------------------------------------------------------- */
async function p42LoadDataResidency() {
    const el = document.getElementById('p42DataResidency');
    if (!el) return;

    try {
        const res  = await fetch('/api/data-residency');
        const data = await res.json();

        el.innerHTML = (data.regions || []).map(r => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:8px;margin-bottom:6px;">
            <div style="flex:1;">
                <div style="font-size:12px;font-weight:600;color:${r.available ? 'var(--text)' : 'var(--text-muted)'};">${r.label}</div>
                <div style="font-size:10px;color:var(--text-muted);">${(r.compliance || []).join(' · ')}</div>
            </div>
            <span style="font-size:10px;padding:2px 7px;border-radius:999px;background:${r.available ? 'rgba(0,214,143,0.1)' : 'rgba(255,255,255,0.05)'};color:${r.available ? '#00d68f' : 'var(--text-muted)'};">
                ${r.available ? '✓ Available' : 'Post-acquisition'}
            </span>
        </div>`).join('');
    } catch(e) {}
}

/* ---------------------------------------------------------
   42.5 — REGIONS
--------------------------------------------------------- */
async function p42LoadRegions() {
    const el = document.getElementById('p42Regions');
    if (!el) return;

    try {
        const res  = await fetch('/api/regions');
        const data = await res.json();

        el.innerHTML = (data.available_regions || []).map(r => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:8px;margin-bottom:6px;">
            <div style="width:8px;height:8px;border-radius:50%;background:${r.status === 'active' ? '#00d68f' : 'rgba(255,255,255,0.15)'};flex-shrink:0;"></div>
            <div style="flex:1;">
                <div style="font-size:12px;font-weight:600;color:var(--text);">${r.label}</div>
                <div style="font-size:10px;color:var(--text-muted);">${r.latency_ms ? `${r.latency_ms}ms` : 'Post-acquisition'}</div>
            </div>
            <span style="font-size:10px;color:${r.status === 'active' ? '#00d68f' : 'var(--text-muted)'};">${r.status}</span>
        </div>`).join('');
    } catch(e) {}
}

/* ---------------------------------------------------------
   42.6 — LINKEDIN CONNECT BUTTON
--------------------------------------------------------- */
function p42ConnectLinkedIn() {
    window.location.href = '/auth/linkedin';
}