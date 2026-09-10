/* ============================================================
   PHASE 43 — TALENT GRAPH ENGINE + BILLING FULL FLOW
   Graph builder · Similarity search · Lookalike candidates
   Hidden connections · Graph analytics · Billing + Stripe
   ============================================================ */

console.log('[Phase 43] Talent Graph + Billing loaded ✓');

document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('p43GraphAnalytics')) p43LoadGraphAnalytics();
    if (document.getElementById('p43BillingStatus'))  p43LoadBillingStatus();
    if (document.getElementById('p43BillingPlans'))   p43LoadBillingPlans();
});

/* ---------------------------------------------------------
   43.1 — BUILD GRAPH
--------------------------------------------------------- */
async function p43BuildGraph() {
    const btn = document.getElementById('p43BuildBtn');
    const el  = document.getElementById('p43BuildResult');
    if (btn) { btn.textContent = '⏳ Building...'; btn.disabled = true; }

    try {
        const res  = await fetch('/api/graph/build', { method: 'POST' });
        const data = await res.json();
        if (el) el.innerHTML = `
        <div style="padding:10px;background:rgba(0,214,143,0.06);border:1px solid rgba(0,214,143,0.2);border-radius:8px;font-size:12px;margin-top:8px;">
            ✅ Graph built — <strong>${data.nodes_created}</strong> nodes · <strong>${data.edges_created}</strong> edges · <strong>${data.candidates}</strong> candidates
        </div>`;
        p43LoadGraphAnalytics();
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:#ff4d6d;font-size:12px;margin-top:8px;">Graph build failed</div>';
    } finally {
        if (btn) { btn.textContent = '🔨 Build Talent Graph'; btn.disabled = false; }
    }
}

/* ---------------------------------------------------------
   43.2 — GRAPH ANALYTICS
--------------------------------------------------------- */
async function p43LoadGraphAnalytics() {
    const el = document.getElementById('p43GraphAnalytics');
    if (!el) return;

    try {
        const res  = await fetch('/api/graph/analytics');
        const data = await res.json();

        el.innerHTML = `
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px;">
            <div style="text-align:center;padding:10px;background:rgba(77,159,255,0.05);border:1px solid rgba(77,159,255,0.1);border-radius:8px;">
                <div style="font-size:10px;color:var(--text-muted);margin-bottom:4px;">Nodes</div>
                <div style="font-size:20px;font-weight:800;color:#4d9fff;">${data.total_nodes || 0}</div>
            </div>
            <div style="text-align:center;padding:10px;background:rgba(0,214,143,0.05);border:1px solid rgba(0,214,143,0.1);border-radius:8px;">
                <div style="font-size:10px;color:var(--text-muted);margin-bottom:4px;">Edges</div>
                <div style="font-size:20px;font-weight:800;color:#00d68f;">${data.total_edges || 0}</div>
            </div>
            <div style="text-align:center;padding:10px;background:rgba(167,139,250,0.05);border:1px solid rgba(167,139,250,0.1);border-radius:8px;">
                <div style="font-size:10px;color:var(--text-muted);margin-bottom:4px;">Avg Similarity</div>
                <div style="font-size:20px;font-weight:800;color:#a78bfa;">${data.avg_similarity || 0}%</div>
            </div>
            <div style="text-align:center;padding:10px;background:rgba(245,166,35,0.05);border:1px solid rgba(245,166,35,0.1);border-radius:8px;">
                <div style="font-size:10px;color:var(--text-muted);margin-bottom:4px;">Coverage</div>
                <div style="font-size:20px;font-weight:800;color:#f5a623;">${data.graph_coverage || 0}%</div>
            </div>
        </div>
        ${(data.insights || []).map(i => `
        <div style="padding:8px 10px;background:rgba(77,159,255,0.04);border-left:3px solid #4d9fff;border-radius:4px;font-size:11px;color:rgba(200,220,255,0.7);margin-bottom:6px;">
            💡 ${i}
        </div>`).join('')}`;
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Build the graph first</div>';
    }
}

/* ---------------------------------------------------------
   43.3 — SIMILAR CANDIDATES SEARCH
--------------------------------------------------------- */
async function p43FindSimilar() {
    const candidateId = document.getElementById('p43SimilarInput')?.value?.trim();
    const el          = document.getElementById('p43SimilarResults');
    if (!candidateId || !el) return;

    el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Searching...</div>';

    try {
        const res  = await fetch(`/api/graph/similar/candidate?id=${candidateId}`);
        const data = await res.json();
        const results = data.similar || [];

        if (!results.length) {
            el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">No similar candidates found — build the graph first</div>';
            return;
        }

        el.innerHTML = results.map(c => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;margin-bottom:6px;">
            <div style="font-size:14px;">${c.tier === 'gold' ? '🥇' : c.tier === 'silver' ? '🥈' : '🥉'}</div>
            <div style="flex:1;">
                <div style="font-size:12px;font-weight:600;color:var(--text);">${c.name}</div>
                <div style="font-size:10px;color:var(--text-muted);">${c.role || '—'}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:14px;font-weight:800;color:#a78bfa;">${c.similarity}%</div>
                <div style="font-size:10px;color:var(--text-muted);">similar</div>
            </div>
        </div>`).join('');
    } catch(e) {
        el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Search unavailable</div>';
    }
}

/* ---------------------------------------------------------
   43.4 — LOOKALIKE RECOMMENDATIONS
--------------------------------------------------------- */
async function p43FindLookalikes() {
    const role = document.getElementById('p43LookalikeInput')?.value?.trim();
    const el   = document.getElementById('p43LookalikeResults');
    if (!role || !el) return;

    el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Finding lookalikes...</div>';

    try {
        const res  = await fetch(`/api/graph/recommend/candidates?role=${encodeURIComponent(role)}`);
        const data = await res.json();
        const results = data.lookalikes || [];

        if (!results.length) {
            el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">No lookalikes found</div>';
            return;
        }

        el.innerHTML = results.map(c => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;margin-bottom:6px;">
            <div style="font-size:14px;">${c.tier === 'gold' ? '🥇' : c.tier === 'silver' ? '🥈' : '🥉'}</div>
            <div style="flex:1;">
                <div style="font-size:12px;font-weight:600;color:var(--text);">${c.name}</div>
                <div style="font-size:10px;color:var(--text-muted);">${c.role || '—'}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:14px;font-weight:800;color:#00d68f;">${c.match}%</div>
                <div style="font-size:10px;color:var(--text-muted);">match</div>
            </div>
        </div>`).join('');
    } catch(e) {
        el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Search unavailable</div>';
    }
}

/* ---------------------------------------------------------
   43.5 — BILLING STATUS
--------------------------------------------------------- */
async function p43LoadBillingStatus() {
    const el = document.getElementById('p43BillingStatus');
    if (!el) return;

    try {
        const res  = await fetch('/api/billing/status');
        const data = await res.json();
        const u    = data.usage || {};

        el.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <div>
                <div style="font-size:18px;font-weight:800;color:#4d9fff;">${data.plan_name || 'Free'}</div>
                <div style="font-size:12px;color:var(--text-muted);">$${data.price_month || 0}/month</div>
            </div>
            <button onclick="p43OpenBillingPortal()" style="padding:8px 14px;border-radius:8px;border:1px solid rgba(29,110,245,0.3);background:rgba(29,110,245,0.1);color:#4d9fff;font-size:12px;cursor:pointer;">Manage Billing</button>
        </div>
        ${Object.entries(u).map(([key, val]) => `
        <div style="margin-bottom:8px;">
            <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:3px;">
                <span style="color:var(--text-muted);text-transform:capitalize;">${key.replace('_',' ')}</span>
                <span style="color:var(--text-soft);">${val.used} / ${val.limit === -1 ? '∞' : val.limit}</span>
            </div>
            <div style="height:5px;background:rgba(255,255,255,0.06);border-radius:999px;overflow:hidden;">
                <div style="height:100%;width:${Math.min(val.pct || 0, 100)}%;background:${(val.pct || 0) > 80 ? '#ff4d6d' : '#4d9fff'};border-radius:999px;transition:width 0.8s;"></div>
            </div>
        </div>`).join('')}
        <div style="margin-top:10px;font-size:11px;color:var(--text-muted);">Period: ${new Date(data.period_start).toLocaleDateString()}</div>`;
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Billing data unavailable</div>';
    }
}

/* ---------------------------------------------------------
   43.6 — BILLING PLANS
--------------------------------------------------------- */
async function p43LoadBillingPlans() {
    const el = document.getElementById('p43BillingPlans');
    if (!el) return;

    try {
        const res  = await fetch('/api/billing/plans');
        const data = await res.json();
        const plans = data.plans || [];

        el.innerHTML = plans.map(p => `
        <div style="padding:14px;background:rgba(255,255,255,0.02);border:1px solid ${p.price_month >= 299 ? 'rgba(167,139,250,0.2)' : 'rgba(255,255,255,0.07)'};border-radius:10px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <div style="font-size:14px;font-weight:700;color:var(--text);">${p.name}</div>
                <div style="font-size:16px;font-weight:800;color:#4d9fff;">$${p.price_month}<span style="font-size:10px;color:var(--text-muted);">/mo</span></div>
            </div>
            <div style="font-size:10px;color:var(--text-muted);margin-bottom:10px;">${(p.features || []).slice(0,2).join(' · ')}</div>
            ${p.price_month > 0 ? `
            <button onclick="p43Upgrade('${p.name.toLowerCase()}')" style="width:100%;padding:7px;border-radius:6px;border:1px solid rgba(29,110,245,0.3);background:rgba(29,110,245,0.1);color:#4d9fff;font-size:12px;cursor:pointer;font-weight:600;">
                Upgrade to ${p.name}
            </button>` : '<div style="font-size:11px;color:#00d68f;text-align:center;">Current plan</div>'}
        </div>`).join('');
    } catch(e) {}
}

async function p43Upgrade(plan) {
    try {
        const res  = await fetch('/api/billing/checkout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan, return_url: window.location.href })
        });
        const data = await res.json();
        if (data.checkout_url) {
            window.location.href = data.checkout_url;
        } else if (data.demo) {
            alert(`Demo mode: ${data.message}`);
        } else {
            alert(data.error || 'Checkout failed');
        }
    } catch(e) { alert('Checkout unavailable'); }
}

async function p43OpenBillingPortal() {
    try {
        const res  = await fetch('/api/billing/portal', { method: 'POST' });
        const data = await res.json();
        if (data.portal_url) window.location.href = data.portal_url;
        else alert(data.message || data.error || 'Portal unavailable');
    } catch(e) { alert('Billing portal unavailable'); }
}