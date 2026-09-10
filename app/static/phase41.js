/* ============================================================
   PHASE 41 — POST-ACQUISITION INTEGRATION
   Partner Marketplace · Compliance · Mobile SDK · Webhooks 2.0
   ============================================================ */

console.log('[Phase 41] Post-Acquisition Integration loaded ✓');

document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('p41PartnerGrid'))    p41LoadPartners();
    if (document.getElementById('p41ComplianceLogs')) p41LoadComplianceLogs();
    if (document.getElementById('p41WebhookDLQ'))     p41LoadWebhookDLQ();
    if (document.getElementById('p41MobileSDK'))      p41LoadMobileSDK();
    if (document.getElementById('p41AIPaths'))        p41LoadAIPaths();
});

/* ---------------------------------------------------------
   41.1 — PARTNER MARKETPLACE
--------------------------------------------------------- */
async function p41LoadPartners() {
    const el = document.getElementById('p41PartnerGrid');
    if (!el) return;

    try {
        const [catalogRes, installedRes] = await Promise.all([
            fetch('/api/partners/catalog'),
            fetch('/api/partners/installed'),
        ]);
        const catalog   = await catalogRes.json();
        const installed = await installedRes.json();
        const installedKeys = new Set((installed.installed || []).map(i => i.partner_key));

        el.innerHTML = (catalog.partners || []).map(p => {
            const isInstalled = installedKeys.has(p.name?.toLowerCase());
            const statusColor = p.status === 'available' ? '#00d68f' : p.status === 'partner_pending' ? '#4d9fff' : '#f5a623';
            return `
            <div style="padding:14px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.07);border-radius:10px;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                    <span style="font-size:20px;">${p.icon}</span>
                    <div>
                        <div style="font-size:13px;font-weight:700;color:var(--text);">${p.name}</div>
                        <div style="font-size:10px;color:var(--text-muted);">${p.category}</div>
                    </div>
                    <span style="margin-left:auto;font-size:10px;padding:2px 7px;border-radius:999px;background:${statusColor}15;color:${statusColor};border:1px solid ${statusColor}33;">${p.status.replace('_',' ')}</span>
                </div>
                <div style="font-size:11px;color:rgba(200,220,255,0.6);margin-bottom:10px;">${p.description}</div>
                ${p.status === 'available' ? `
                <button onclick="p41TogglePartner('${p.name.toLowerCase()}', ${isInstalled})" style="width:100%;padding:6px;border-radius:6px;border:1px solid ${isInstalled ? 'rgba(255,77,109,0.3)' : 'rgba(0,214,143,0.3)'};background:${isInstalled ? 'rgba(255,77,109,0.08)' : 'rgba(0,214,143,0.08)'};color:${isInstalled ? '#ff4d6d' : '#00d68f'};font-size:11px;cursor:pointer;">
                    ${isInstalled ? '✕ Uninstall' : '+ Install'}
                </button>` : `<div style="font-size:10px;color:var(--text-muted);text-align:center;padding:4px;">Available post-acquisition</div>`}
            </div>`;
        }).join('');
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Partner catalog unavailable</div>';
    }
}

async function p41TogglePartner(partnerKey, isInstalled) {
    try {
        const endpoint = isInstalled ? '/api/partners/uninstall' : '/api/partners/install';
        const res  = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ partner_key: partnerKey, config: {} })
        });
        const data = await res.json();
        if (data.ok) p41LoadPartners();
        else alert(data.error || 'Operation failed');
    } catch(e) {}
}

/* ---------------------------------------------------------
   41.2 — COMPLIANCE AUDIT LOG
--------------------------------------------------------- */
async function p41LoadComplianceLogs() {
    const el = document.getElementById('p41ComplianceLogs');
    if (!el) return;

    try {
        const res  = await fetch('/api/compliance/audit-log');
        const data = await res.json();
        const logs = data.logs || [];

        if (!logs.length) {
            el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;text-align:center;padding:16px;">No compliance events yet</div>';
            return;
        }

        el.innerHTML = `
        <table style="width:100%;border-collapse:collapse;font-size:11px;">
            <thead>
                <tr style="color:var(--text-muted);border-bottom:1px solid rgba(255,255,255,0.06);">
                    <th style="text-align:left;padding:6px 8px;">Action</th>
                    <th style="text-align:left;padding:6px 8px;">Resource</th>
                    <th style="text-align:left;padding:6px 8px;">User</th>
                    <th style="text-align:left;padding:6px 8px;">Time</th>
                </tr>
            </thead>
            <tbody>
                ${logs.slice(0,20).map(l => `
                <tr style="border-bottom:1px solid rgba(255,255,255,0.03);">
                    <td style="padding:6px 8px;color:#4d9fff;">${l.action}</td>
                    <td style="padding:6px 8px;color:var(--text-soft);">${l.resource || '—'}</td>
                    <td style="padding:6px 8px;color:var(--text-muted);">${l.user_id ? l.user_id.slice(0,8)+'...' : 'system'}</td>
                    <td style="padding:6px 8px;color:var(--text-muted);">${new Date(l.created_at).toLocaleString()}</td>
                </tr>`).join('')}
            </tbody>
        </table>`;
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Audit log unavailable — admin access required</div>';
    }
}

async function p41ExportData() {
    try {
        const res  = await fetch('/api/compliance/export');
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href = url; a.download = 'aitmp-gdpr-export.json'; a.click();
        URL.revokeObjectURL(url);
    } catch(e) { alert('Export failed — admin access required'); }
}

/* ---------------------------------------------------------
   41.3 — WEBHOOK DLQ
--------------------------------------------------------- */
async function p41LoadWebhookDLQ() {
    const el = document.getElementById('p41WebhookDLQ');
    if (!el) return;

    try {
        const res  = await fetch('/api/webhooks/failures');
        const data = await res.json();
        const failures = data.failures || [];

        if (!failures.length) {
            el.innerHTML = '<div style="color:#00d68f;font-size:12px;">✓ No failed webhooks</div>';
            return;
        }

        el.innerHTML = failures.map(f => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px;background:rgba(255,77,109,0.04);border:1px solid rgba(255,77,109,0.15);border-radius:8px;margin-bottom:6px;">
            <div style="flex:1;">
                <div style="font-size:12px;font-weight:600;color:var(--text);">${f.event_type}</div>
                <div style="font-size:10px;color:#ff4d6d;">${f.error || 'Unknown error'} · ${f.attempts} attempts</div>
            </div>
            <button onclick="p41ReplayWebhook('${f.id}',this)" style="font-size:11px;padding:4px 10px;border-radius:6px;border:1px solid rgba(77,159,255,0.3);background:rgba(77,159,255,0.08);color:#4d9fff;cursor:pointer;">↺ Replay</button>
        </div>`).join('');
    } catch(e) {}
}

async function p41ReplayWebhook(dlqId, btn) {
    if (btn) { btn.textContent = '⏳'; btn.disabled = true; }
    try {
        const res  = await fetch(`/api/webhooks/replay/${dlqId}`, { method: 'POST' });
        const data = await res.json();
        if (data.ok) {
            btn?.closest('div[style]')?.remove();
            p41LoadWebhookDLQ();
        }
    } catch(e) {}
    if (btn) { btn.textContent = '↺ Replay'; btn.disabled = false; }
}

/* ---------------------------------------------------------
   41.4 — MOBILE SDK DISPLAY
--------------------------------------------------------- */
async function p41LoadMobileSDK() {
    const el = document.getElementById('p41MobileSDK');
    if (!el) return;

    try {
        const [swift, kotlin] = await Promise.all([
            fetch('/api/mobile/sdk/swift').then(r => r.json()),
            fetch('/api/mobile/sdk/kotlin').then(r => r.json()),
        ]);

        el.innerHTML = `
        <div style="margin-bottom:16px;">
            <div style="display:flex;gap:6px;margin-bottom:8px;">
                <button onclick="p41ShowSDK('swift')" id="p41SwiftBtn" style="padding:6px 14px;border-radius:6px;border:1px solid rgba(29,110,245,0.4);background:rgba(29,110,245,0.15);color:#4d9fff;font-size:12px;cursor:pointer;">🍎 Swift (iOS)</button>
                <button onclick="p41ShowSDK('kotlin')" id="p41KotlinBtn" style="padding:6px 14px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:transparent;color:var(--text-muted);font-size:12px;cursor:pointer;">🤖 Kotlin (Android)</button>
            </div>
            <pre id="p41SwiftCode" style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:14px;font-size:11px;color:#00d68f;overflow-x:auto;max-height:260px;overflow-y:auto;">${swift.snippet}</pre>
            <pre id="p41KotlinCode" style="display:none;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:14px;font-size:11px;color:#a78bfa;overflow-x:auto;max-height:260px;overflow-y:auto;">${kotlin.snippet}</pre>
        </div>
        <div style="font-size:11px;color:var(--text-muted);">Base URL: <code style="color:#4d9fff;">https://aitmp.io/api/mobile/v1</code> &nbsp;·&nbsp; Auth: Bearer token &nbsp;·&nbsp; Target latency: &lt;100ms</div>`;
    } catch(e) {}
}

function p41ShowSDK(lang) {
    document.getElementById('p41SwiftCode').style.display  = lang === 'swift'  ? 'block' : 'none';
    document.getElementById('p41KotlinCode').style.display = lang === 'kotlin' ? 'block' : 'none';
    document.getElementById('p41SwiftBtn').style.background  = lang === 'swift'  ? 'rgba(29,110,245,0.15)' : 'transparent';
    document.getElementById('p41KotlinBtn').style.background = lang === 'kotlin' ? 'rgba(29,110,245,0.15)' : 'transparent';
}

/* ---------------------------------------------------------
   41.5 — AI HOT/COLD PATH DISPLAY
--------------------------------------------------------- */
async function p41LoadAIPaths() {
    const el = document.getElementById('p41AIPaths');
    if (!el) return;

    try {
        const res  = await fetch('/api/ai/path?action=scoring');
        const data = await res.json();

        el.innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div style="padding:12px;background:rgba(0,214,143,0.05);border:1px solid rgba(0,214,143,0.15);border-radius:8px;">
                <div style="font-size:11px;font-weight:700;color:#00d68f;margin-bottom:8px;">⚡ HOT PATH (&lt;100ms)</div>
                ${(data.hot_actions||[]).map(a => `<div style="font-size:11px;color:var(--text-muted);padding:2px 0;">• ${a}</div>`).join('')}
                <div style="margin-top:8px;font-size:10px;color:#00d68f;">Model: GPT-4o · Azure Function</div>
            </div>
            <div style="padding:12px;background:rgba(167,139,250,0.05);border:1px solid rgba(167,139,250,0.15);border-radius:8px;">
                <div style="font-size:11px;font-weight:700;color:#a78bfa;margin-bottom:8px;">🧠 COLD PATH (async)</div>
                ${(data.cold_actions||[]).map(a => `<div style="font-size:11px;color:var(--text-muted);padding:2px 0;">• ${a}</div>`).join('')}
                <div style="margin-top:8px;font-size:10px;color:#a78bfa;">Model: GPT-4o · Background queue</div>
            </div>
        </div>`;
    } catch(e) {}
}