/* ============================================================
   PHASE 37 — FORECAST 2.0 + RECRUITER OS
   Funnel · Confidence Bands · Scenario Simulator · Bottlenecks
   Smart Search · Candidate Timeline · Comparison
   ============================================================ */

console.log('[Phase 37] Forecast 2.0 + Recruiter OS loaded ✓');

// ── Auto-load when analytics page is ready ────────────────
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('p37FunnelStages')) {
        p37LoadAll();
    }
});

async function p37LoadAll() {
    await Promise.all([
        p37LoadFunnel(),
        p37LoadConfidenceBands(),
        p37LoadBottlenecks(),
    ]);
}

/* ---------------------------------------------------------
   37.1 — FUNNEL PANEL
--------------------------------------------------------- */
async function p37LoadFunnel() {
    const el = document.getElementById('p37FunnelStages');
    if (!el) return;

    try {
        const res  = await fetch('/api/forecast/funnel');
        const data = await res.json();
        const stages = data.stages || [];
        const max    = stages[0]?.predicted_count || 1;

        el.innerHTML = stages.map(s => {
            const width      = Math.round((s.predicted_count / max) * 100);
            const color      = s.is_bottleneck ? '#ff4d6d' : s.drop_off_pct > 40 ? '#f5a623' : '#4d9fff';
            const bottleneck = s.is_bottleneck ? '⚠ BOTTLENECK' : '';
            return `
            <div style="margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px;">
                    <span style="color:var(--text-soft);font-weight:600;">${s.stage} ${bottleneck ? `<span style="color:#ff4d6d;font-size:9px;font-weight:700;">${bottleneck}</span>` : ''}</span>
                    <span style="color:${color};font-weight:700;">${s.predicted_count} <span style="color:var(--text-muted);font-weight:400;">(${s.drop_off_pct}% drop)</span></span>
                </div>
                <div style="height:8px;background:rgba(255,255,255,0.05);border-radius:999px;overflow:hidden;">
                    <div style="height:100%;width:${width}%;background:${color};border-radius:999px;transition:width 0.8s ease;"></div>
                </div>
                <div style="font-size:10px;color:var(--text-muted);margin-top:2px;">${s.avg_time_days} days avg · ${s.conversion_pct}% conversion</div>
            </div>`;
        }).join('');

        const summary = document.getElementById('p37FunnelSummary');
        if (summary) {
            summary.innerHTML = `
                <span style="color:#4d9fff;">Predicted hire: <strong>${data.predicted_hire}</strong></span> &nbsp;·&nbsp;
                <span style="color:#f5a623;">Total time: <strong>${data.total_days}d</strong></span> &nbsp;·&nbsp;
                <span style="color:var(--text-muted);">Outreach needed: <strong>${data.outreach_needed}</strong></span>`;
        }
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Funnel data unavailable</div>';
    }
}

/* ---------------------------------------------------------
   37.2 — CONFIDENCE BANDS
--------------------------------------------------------- */
async function p37LoadConfidenceBands() {
    const el = document.getElementById('p37ConfidenceChart');
    if (!el) return;

    try {
        const res  = await fetch('/api/forecast/confidence');
        const data = await res.json();
        const days = data.days || [];
        const curves = data.curves || {};

        // Simple SVG line chart
        const w = 340, h = 120, pad = 20;
        const xScale = d => pad + (d / 30) * (w - pad * 2);
        const yScale = v => h - pad - (v / 100) * (h - pad * 2);

        const toPath = arr => arr.map((v, i) => `${i === 0 ? 'M' : 'L'}${xScale(days[i])},${yScale(v)}`).join(' ');

        el.innerHTML = `
        <svg viewBox="0 0 ${w} ${h}" style="width:100%;height:auto;">
            <!-- Confidence band fill -->
            <path d="${toPath(curves.low)} L${xScale(30)},${yScale(curves.high[29])} ${[...curves.high].reverse().map((v,i) => `L${xScale(days[29-i])},${yScale(v)}`).join(' ')} Z"
                fill="rgba(77,159,255,0.08)" />
            <!-- Low curve -->
            <path d="${toPath(curves.low)}" fill="none" stroke="#ff4d6d" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.6"/>
            <!-- High curve -->
            <path d="${toPath(curves.high)}" fill="none" stroke="#00d68f" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.6"/>
            <!-- Expected curve -->
            <path d="${toPath(curves.expected)}" fill="none" stroke="#4d9fff" stroke-width="2"/>
            <!-- Labels -->
            <text x="${pad}" y="${h-4}" fill="rgba(255,255,255,0.3)" font-size="9">Day 1</text>
            <text x="${w-pad-20}" y="${h-4}" fill="rgba(255,255,255,0.3)" font-size="9">Day 30</text>
        </svg>
        <div style="display:flex;gap:12px;margin-top:6px;font-size:10px;">
            <span style="color:#4d9fff;">— Expected (p50: ${data.bands?.p50}d)</span>
            <span style="color:#00d68f;">— Best case (p80: ${data.bands?.p80}d)</span>
            <span style="color:#ff4d6d;">— Worst case (p95: ${data.bands?.p95}d)</span>
        </div>
        <div style="margin-top:6px;font-size:11px;color:var(--text-muted);">
            Confidence score: <strong style="color:#4d9fff;">${Math.round((data.confidence_score || 0) * 100)}%</strong> &nbsp;·&nbsp;
            Volatility: <strong style="color:#f5a623;">${data.volatility_score || 0}pts</strong>
        </div>`;
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Confidence data unavailable</div>';
    }
}

/* ---------------------------------------------------------
   37.3 — SCENARIO SIMULATOR
--------------------------------------------------------- */
async function p37RunScenario() {
    const outreachDelta  = parseFloat(document.getElementById('p37OutreachSlider')?.value || 0) / 100;
    const responseDelta  = parseFloat(document.getElementById('p37ResponseSlider')?.value || 0) / 100;
    const recruiterLoad  = parseFloat(document.getElementById('p37LoadSlider')?.value || 100) / 100;
    const resultEl       = document.getElementById('p37ScenarioResult');
    const btn            = document.getElementById('p37ScenarioBtn');

    if (btn) { btn.textContent = '⏳ Simulating...'; btn.disabled = true; }

    try {
        const res  = await fetch('/api/forecast/scenario', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ outreach_delta: outreachDelta, response_delta: responseDelta, recruiter_load: recruiterLoad })
        });
        const data = await res.json();
        const s    = data.scenario || {};
        const b    = data.baseline || {};
        const imp  = data.improvement_pct || 0;
        const color = imp > 0 ? '#00d68f' : '#ff4d6d';
        const arrow = imp > 0 ? '↓' : '↑';

        if (resultEl) {
            resultEl.innerHTML = `
            <div style="padding:12px;background:rgba(29,110,245,0.06);border:1px solid rgba(29,110,245,0.15);border-radius:8px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                    <div style="font-size:13px;font-weight:700;color:var(--text);">Scenario Result</div>
                    <div style="font-size:18px;font-weight:800;color:${color};">${arrow} ${Math.abs(imp)}% ${imp > 0 ? 'faster' : 'slower'}</div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">
                    <div style="padding:8px;background:rgba(255,255,255,0.03);border-radius:6px;">
                        <div style="font-size:10px;color:var(--text-muted);">Time to Hire</div>
                        <div style="font-size:16px;font-weight:700;color:${color};">${s.time_to_hire}d <span style="font-size:11px;color:var(--text-muted);">was ${b.time_to_hire}d</span></div>
                    </div>
                    <div style="padding:8px;background:rgba(255,255,255,0.03);border-radius:6px;">
                        <div style="font-size:10px;color:var(--text-muted);">Risk Score</div>
                        <div style="font-size:16px;font-weight:700;color:${s.risk_score === 'HIGH' ? '#ff4d6d' : s.risk_score === 'MEDIUM' ? '#f5a623' : '#00d68f'};">${s.risk_score}</div>
                    </div>
                </div>
                <div style="font-size:11px;color:rgba(200,220,255,0.6);font-style:italic;">"${data.narrative}"</div>
            </div>`;
        }
    } catch(e) {
        if (resultEl) resultEl.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Simulation unavailable</div>';
    } finally {
        if (btn) { btn.textContent = '▶ Run Simulation'; btn.disabled = false; }
    }
}

// Update slider labels
function p37UpdateSlider(id, labelId, suffix) {
    const val = document.getElementById(id)?.value;
    const label = document.getElementById(labelId);
    if (label && val !== undefined) label.textContent = val + suffix;
}

/* ---------------------------------------------------------
   37.4 — BOTTLENECK DETECTOR
--------------------------------------------------------- */
async function p37LoadBottlenecks() {
    const el = document.getElementById('p37BottleneckCard');
    if (!el) return;

    try {
        const res  = await fetch('/api/forecast/bottlenecks');
        const data = await res.json();
        const b    = data.bottleneck;

        if (!b) {
            el.innerHTML = '<div style="color:#00d68f;font-size:12px;">✓ No bottlenecks detected</div>';
            return;
        }

        const healthColor = data.funnel_health === 'CRITICAL' ? '#ff4d6d' : data.funnel_health === 'WARNING' ? '#f5a623' : '#00d68f';

        el.innerHTML = `
        <div style="padding:12px;background:rgba(255,77,109,0.05);border:1px solid rgba(255,77,109,0.2);border-radius:8px;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                <div style="font-size:12px;font-weight:700;color:#ff4d6d;">⚠ Bottleneck: ${b.stage} Stage</div>
                <span style="font-size:10px;padding:2px 7px;border-radius:999px;background:${healthColor}22;color:${healthColor};border:1px solid ${healthColor}44;">${data.funnel_health}</span>
            </div>
            <div style="font-size:12px;color:var(--text-soft);margin-bottom:6px;">${b.drop_off_pct}% drop-off · ${b.predicted_count} candidates stalling</div>
            <div style="padding:8px;background:rgba(255,255,255,0.03);border-radius:6px;margin-bottom:6px;">
                <div style="font-size:10px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:3px;">Root Cause</div>
                <div style="font-size:11px;color:rgba(200,220,255,0.7);">${b.root_cause}</div>
            </div>
            <div style="padding:8px;background:rgba(0,214,143,0.05);border:1px solid rgba(0,214,143,0.12);border-radius:6px;">
                <div style="font-size:10px;font-weight:700;color:#00d68f;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:3px;">Fix</div>
                <div style="font-size:11px;color:rgba(200,220,255,0.7);">${b.recommendation}</div>
            </div>
        </div>`;
    } catch(e) {
        if (el) el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Bottleneck data unavailable</div>';
    }
}

/* ---------------------------------------------------------
   37.5 — SMART SEARCH
--------------------------------------------------------- */
async function p37SmartSearch(query) {
    const el = document.getElementById('p37SearchResults');
    if (!el || !query) return;

    el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Searching...</div>';

    try {
        const res  = await fetch(`/api/search/candidates?q=${encodeURIComponent(query)}`);
        const data = await res.json();

        if (!data.results?.length) {
            el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">No candidates found</div>';
            return;
        }

        el.innerHTML = data.results.map(c => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:8px;margin-bottom:6px;">
            <div style="width:32px;height:32px;border-radius:50%;background:${c.tier === 'gold' ? 'rgba(245,166,35,0.2)' : c.tier === 'silver' ? 'rgba(141,153,174,0.2)' : 'rgba(139,92,246,0.2)'};display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0;">
                ${c.tier === 'gold' ? '🥇' : c.tier === 'silver' ? '🥈' : '🥉'}
            </div>
            <div style="flex:1;">
                <div style="font-size:13px;font-weight:600;color:var(--text);">${c.name}</div>
                <div style="font-size:11px;color:var(--text-muted);">${c.role || '—'}</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:16px;font-weight:800;color:#4d9fff;">${c.match_score || 0}</div>
                <div style="font-size:10px;color:var(--text-muted);">score</div>
            </div>
        </div>`).join('');
    } catch(e) {
        el.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Search unavailable</div>';
    }
}

/* ---------------------------------------------------------
   37.6 — CANDIDATE TIMELINE
--------------------------------------------------------- */
async function p37ShowTimeline(candidateId, candidateName) {
    try {
        const res  = await fetch(`/api/candidates/${candidateId}/timeline`);
        const data = await res.json();
        const events = data.events || [];

        const modal = document.createElement('div');
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center;';
        modal.innerHTML = `
        <div style="background:#0d1829;border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:24px;max-width:480px;width:90%;max-height:80vh;overflow-y:auto;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                <div style="font-size:16px;font-weight:700;color:var(--text);">📋 ${candidateName} — Timeline</div>
                <button onclick="this.closest('div[style]').remove()" style="background:transparent;border:none;color:var(--text-muted);cursor:pointer;font-size:18px;">×</button>
            </div>
            ${events.length === 0 ? '<div style="color:var(--text-muted);font-size:12px;text-align:center;padding:20px;">No events yet</div>' :
            events.map(e => `
            <div style="display:flex;gap:12px;margin-bottom:12px;">
                <div style="font-size:20px;flex-shrink:0;">${e.icon}</div>
                <div>
                    <div style="font-size:13px;font-weight:600;color:var(--text);">${e.label}</div>
                    ${e.detail ? `<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${e.detail}</div>` : ''}
                    <div style="font-size:10px;color:rgba(255,255,255,0.25);margin-top:2px;">${new Date(e.date).toLocaleDateString()}</div>
                </div>
            </div>`).join('')}
        </div>`;
        document.body.appendChild(modal);
        modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    } catch(e) {}
}