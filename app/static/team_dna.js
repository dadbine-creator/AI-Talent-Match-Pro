/* ============================================================
   team_dna.js — Team DNA panel for the workspace
   Additive: everything is namespaced under window.TeamDNA and the
   tdna* globals the panel's inline handlers call.

   Reuses the workspace's existing helpers when present (wsToast,
   addCandidateCard) and degrades gracefully when they're not.
   ============================================================ */
(function () {
    'use strict';

    var state = {
        roles: [],
        roleId: null,
        model: null,
        profiles: [],
        pollTimer: null,
        jobId: null,
        busy: false
    };

    /* ── helpers ─────────────────────────────────────────── */

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function toast(msg, kind) {
        if (typeof window.wsToast === 'function') { window.wsToast(msg, kind || ''); }
        else { console.log('[Team DNA]', msg); }
    }

    function el(id) { return document.getElementById(id); }

    /** Read an error message out of a fetch Response, honestly.
     *  Never invents a reason — falls back to the status code. */
    function errorFrom(res, body) {
        if (body && (body.detail || body.error)) return body.detail || body.error;
        return 'Request failed (' + res.status + ')';
    }

    async function api(path, options) {
        var res = await fetch(path, options);
        var body = null;
        try { body = await res.json(); } catch (e) { /* non-JSON */ }
        if (!res.ok) { var err = new Error(errorFrom(res, body)); err.status = res.status; err.body = body; throw err; }
        return body;
    }

    /* ── panel open/close ────────────────────────────────── */

    window.openTeamDNA = function () {
        var overlay = el('tdnaOverlay');
        if (!overlay) return;
        overlay.classList.add('open');
        loadRoles();
    };

    window.closeTeamDNA = function () {
        var overlay = el('tdnaOverlay');
        if (overlay) overlay.classList.remove('open');
        stopPolling();
    };

    /* ── roles ───────────────────────────────────────────── */

    async function loadRoles() {
        var select = el('tdnaRole');
        if (!select) return;
        try {
            var data = await api('/api/team-dna-roles');
            state.roles = data.roles || [];
        } catch (e) {
            state.roles = [];
            toast(e.message, 'error');
        }

        if (!state.roles.length) {
            select.innerHTML = '<option value="">No roles yet — create one</option>';
            renderBody({ empty: true });
            return;
        }

        select.innerHTML = state.roles.map(function (r) {
            return '<option value="' + esc(r.id) + '">' + esc(r.title) +
                   ' (' + r.dna_profile_count + '/5 exemplars)</option>';
        }).join('');

        if (!state.roleId || !state.roles.some(function (r) { return r.id === state.roleId; })) {
            state.roleId = state.roles[0].id;
        }
        select.value = state.roleId;
        loadModel();
    }

    window.tdnaRoleChanged = function (value) {
        state.roleId = value || null;
        stopPolling();
        if (state.roleId) loadModel();
    };

    window.tdnaCreateRole = async function () {
        var title = prompt('Role title (e.g. "Senior ML Engineer"):');
        if (!title || !title.trim()) return;
        try {
            var created = await api('/api/team-dna-roles', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: title.trim() })
            });
            state.roleId = created.id;
            toast('Role created', 'success');
            loadRoles();
        } catch (e) { toast(e.message, 'error'); }
    };

    /* ── model ───────────────────────────────────────────── */

    async function loadModel() {
        if (!state.roleId) return;
        renderBody({ loading: true });
        try {
            var data = await api('/api/team-dna/' + encodeURIComponent(state.roleId));
            state.model = data;
            state.profiles = data.profiles || [];
            renderBody({ data: data });
        } catch (e) {
            // 503 carries the profile list plus an honest reason the build failed.
            var body = e.body || {};
            state.profiles = body.profiles || [];
            renderBody({ data: body, error: e.message });
        }
    }

    /* ── rendering ───────────────────────────────────────── */

    function renderBody(opts) {
        var host = el('tdnaBody');
        if (!host) return;

        if (opts.loading) {
            host.innerHTML = '<div class="tdna-empty">Reading your team’s profiles…</div>';
            return;
        }
        if (opts.empty) {
            host.innerHTML = '<div class="tdna-empty">' +
                'Create a role first, then add 2–10 people already on your team who are great at it.' +
                '</div>';
            return;
        }

        var data = opts.data || {};
        var profiles = data.profiles || [];
        var traits = data.shared_traits || [];
        var ready = profiles.length >= 2;
        var html = '';

        /* exemplars */
        html += '<div class="tdna-section">';
        html += '<div class="tdna-section-title">Your best people — the benchmark</div>';
        if (profiles.length) {
            html += '<div class="tdna-profiles">' + profiles.map(function (p) {
                return '<div class="tdna-profile">' +
                    '<span class="tdna-profile-name">' + esc(p.name) + '</span>' +
                    '<span class="tdna-profile-meta">' + (p.chars || 0) + ' chars · ' + esc(p.source || 'paste') + '</span>' +
                    '<button class="tdna-profile-del" onclick="tdnaDeleteProfile(\'' + esc(p.id) + '\')">Remove</button>' +
                    '</div>';
            }).join('') + '</div>';
        } else {
            html += '<div class="tdna-hint" style="margin-bottom:12px;">' +
                'No exemplars yet. Add 2–10 CVs or profiles of people already on your team who are excellent in this role.' +
                '</div>';
        }
        html += '<div class="tdna-row" style="margin-bottom:14px;">' +
            '<button class="tdna-btn tdna-btn--ghost" onclick="tdnaShowResults()">📊 Results — do the scores predict your hires?</button>' +
            '</div>';

        html += '<div class="tdna-row">' +
            '<span class="tdna-counter' + (ready ? ' ready' : '') + '">' +
                profiles.length + ' of 5 · ' + (ready ? 'ready to build' : 'need at least 2') +
            '</span>' +
            '<button class="tdna-btn tdna-btn--ghost" onclick="tdnaPasteProfile()">Paste a profile</button>' +
            '<button class="tdna-btn tdna-btn--ghost" onclick="el_tdnaExemplarInput().click()">Upload CV</button>' +
            '</div>';
        html += '</div>';

        /* the model */
        if (opts.error) {
            html += '<div class="tdna-section"><div class="tdna-alert">' + esc(opts.error) + '</div></div>';
        } else if (data.built && traits.length) {
            html += '<div class="tdna-section">';
            html += '<div class="tdna-section-title">What good looks like here' +
                    (data.cached ? '' : ' · just rebuilt') + '</div>';
            html += '<div class="tdna-chips">' + traits.map(function (t) {
                var bucket = t.weight >= 8 ? 'high' : (t.weight <= 4 ? 'low' : 'mid');
                return '<span class="tdna-chip" data-w="' + bucket + '" title="' + esc(t.evidence) + '">' +
                    '<b>' + esc(t.trait) + '</b><span class="w">' + t.weight + '</span></span>';
            }).join('') + '</div>';

            if (traits[0] && traits[0].evidence) {
                html += '<div class="tdna-evidence"><strong>Strongest signal — ' +
                    esc(traits[0].trait) + ':</strong> “' + esc(traits[0].evidence) + '”</div>';
            }
            if (data.traits_dropped) {
                html += '<div class="tdna-hint" style="margin-top:8px;">' + data.traits_dropped +
                    ' trait(s) were dropped — no concrete evidence, or they referenced ' +
                    'characteristics we don’t evaluate on.</div>';
            }
            html += '</div>';

            if (data.summary) {
                html += '<div class="tdna-section"><div class="tdna-section-title">Summary</div>' +
                    '<div class="tdna-summary">' + esc(data.summary) + '</div></div>';
            }
            if ((data.career_patterns || []).length) {
                html += '<div class="tdna-section"><div class="tdna-section-title">Career patterns</div>' +
                    '<ul class="tdna-list">' + data.career_patterns.map(function (p) {
                        return '<li>' + esc(p) + '</li>';
                    }).join('') + '</ul></div>';
            }
            if ((data.anti_signals || []).length) {
                html += '<div class="tdna-section"><div class="tdna-section-title">' +
                    'Absent from this team (context, not a rejection rule)</div>' +
                    '<ul class="tdna-list">' + data.anti_signals.map(function (a) {
                        return '<li>' + esc(a) + '</li>';
                    }).join('') + '</ul></div>';
            }
        } else if (data.message) {
            html += '<div class="tdna-section"><div class="tdna-alert">' + esc(data.message) + '</div></div>';
        }

        /* bulk scoring */
        var canScore = !!(data.built && traits.length);
        html += '<div class="tdna-section">';
        html += '<div class="tdna-section-title">Score candidates against this DNA</div>';
        html += '<div class="tdna-drop' + (canScore ? '' : ' disabled') + '" id="tdnaDrop"' +
                (canScore ? ' onclick="el_tdnaBulkInput().click()"' : '') + '>' +
            '<div class="tdna-drop-icon">⬇︎</div>' +
            '<div class="tdna-drop-title">' +
                (canScore ? 'Drop up to 200 CVs here' : 'Build the Team DNA first') + '</div>' +
            '<div class="tdna-drop-sub">' +
                (canScore ? 'PDF, DOCX or TXT · scored 5 at a time against your team’s profile'
                          : 'Add at least 2 exemplar profiles above') + '</div>' +
            '</div>';
        html += '<div class="tdna-progress-wrap" id="tdnaProgressWrap">' +
            '<div class="tdna-progress-bar"><div class="tdna-progress-fill" id="tdnaProgressFill"></div></div>' +
            '<div class="tdna-progress-text"><span id="tdnaProgressText">Starting…</span>' +
            '<span id="tdnaProgressPct">0%</span></div></div>';
        html += '<div id="tdnaErrors"></div>';
        html += '<div class="tdna-results" id="tdnaResults"></div>';
        html += '</div>';

        host.innerHTML = html;
        wireDropzone();
    }

    /* Exposed so inline onclick can reach the hidden file inputs. */
    window.el_tdnaExemplarInput = function () { return el('tdnaExemplarInput'); };
    window.el_tdnaBulkInput = function () { return el('tdnaBulkInput'); };

    /* ── exemplar upload ─────────────────────────────────── */

    window.tdnaPasteProfile = async function () {
        if (!state.roleId) { toast('Pick a role first', 'error'); return; }
        var text = prompt('Paste the CV or profile of someone already on your team who is great at this role:');
        if (!text || !text.trim()) return;
        var name = prompt('Their name (or leave blank):') || '';
        try {
            await api('/api/team-dna/profiles', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    role_id: state.roleId,
                    profiles: [{ name: name.trim() || 'Team member', text: text.trim() }]
                })
            });
            toast('Exemplar added', 'success');
            loadModel();
        } catch (e) { toast(e.message, 'error'); }
    };

    window.tdnaExemplarFiles = async function (input) {
        if (!state.roleId || !input.files || !input.files.length) return;
        var form = new FormData();
        form.append('role_id', state.roleId);
        for (var i = 0; i < input.files.length; i++) form.append('files', input.files[i]);
        input.value = '';
        try {
            var data = await api('/api/team-dna/profiles', { method: 'POST', body: form });
            if ((data.errors || []).length) {
                toast(data.errors.length + ' file(s) could not be read', 'error');
            } else {
                toast('Added ' + (data.added || []).length + ' exemplar(s)', 'success');
            }
            loadModel();
        } catch (e) { toast(e.message, 'error'); }
    };

    window.tdnaDeleteProfile = async function (profileId) {
        if (!confirm('Remove this exemplar? The Team DNA will be rebuilt from the rest.')) return;
        try {
            await api('/api/team-dna/profiles/' + encodeURIComponent(profileId), { method: 'DELETE' });
            toast('Exemplar removed', 'success');
            loadModel();
        } catch (e) { toast(e.message, 'error'); }
    };

    /* ── bulk upload ─────────────────────────────────────── */

    function wireDropzone() {
        var drop = el('tdnaDrop');
        if (!drop || drop.classList.contains('disabled')) return;

        ['dragenter', 'dragover'].forEach(function (evt) {
            drop.addEventListener(evt, function (e) {
                e.preventDefault(); e.stopPropagation(); drop.classList.add('drag');
            });
        });
        ['dragleave', 'drop'].forEach(function (evt) {
            drop.addEventListener(evt, function (e) {
                e.preventDefault(); e.stopPropagation(); drop.classList.remove('drag');
            });
        });
        drop.addEventListener('drop', function (e) {
            var files = e.dataTransfer && e.dataTransfer.files;
            if (files && files.length) startBulk(files);
        });
    }

    window.tdnaBulkFiles = function (input) {
        if (input.files && input.files.length) startBulk(input.files);
        input.value = '';
    };

    async function startBulk(files) {
        if (state.busy) { toast('A batch is already running', ''); return; }
        if (!state.roleId) { toast('Pick a role first', 'error'); return; }

        var form = new FormData();
        form.append('role_id', state.roleId);
        for (var i = 0; i < files.length; i++) form.append('files', files[i]);

        state.busy = true;
        setProgress(0, 'Uploading ' + files.length + ' file(s)…');
        showProgress(true);
        el('tdnaResults').innerHTML = '';
        el('tdnaErrors').innerHTML = '';

        try {
            var data = await api('/api/candidates/bulk', { method: 'POST', body: form });
            state.jobId = data.job_id;
            renderRejected(data.rejected_files || []);
            if (data.rejected) {
                toast(data.rejected + ' file(s) could not be read — scoring the other ' +
                      data.accepted, '');
            }
            setProgress(0, 'Scoring ' + data.accepted + ' candidate(s)…');
            poll();
        } catch (e) {
            state.busy = false;
            showProgress(false);
            toast(e.message, 'error');
            el('tdnaErrors').innerHTML =
                '<div class="tdna-alert">' + esc(e.message) + '</div>';
        }
    }

    function poll() {
        stopPolling();
        state.pollTimer = setInterval(async function () {
            if (!state.jobId) { stopPolling(); return; }
            try {
                var job = await api('/api/candidates/bulk/' + encodeURIComponent(state.jobId));
                setProgress(job.progress || 0,
                    'Scored ' + job.completed + ' of ' + job.total);
                if (job.status === 'complete') {
                    stopPolling();
                    state.busy = false;
                    setProgress(100, 'Scored ' + job.completed + ' of ' + job.total);
                    renderResults(job.results || []);
                    renderRejected(job.failed || []);
                    toast('Ranked ' + (job.results || []).length + ' candidate(s)', 'success');
                } else if (job.status === 'failed') {
                    stopPolling();
                    state.busy = false;
                    showProgress(false);
                    toast(job.error || 'The batch failed', 'error');
                }
            } catch (e) {
                stopPolling();
                state.busy = false;
                showProgress(false);
                toast(e.message, 'error');
            }
        }, 1200);
    }

    function stopPolling() {
        if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
    }

    function showProgress(on) {
        var wrap = el('tdnaProgressWrap');
        if (wrap) wrap.classList.toggle('on', !!on);
    }

    function setProgress(pct, text) {
        var fill = el('tdnaProgressFill'), label = el('tdnaProgressText'), num = el('tdnaProgressPct');
        if (fill) fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
        if (label) label.textContent = text || '';
        if (num) num.textContent = Math.round(pct) + '%';
    }

    function renderRejected(failed) {
        var host = el('tdnaErrors');
        if (!host) return;
        if (!failed.length) { host.innerHTML = ''; return; }
        host.innerHTML = '<div class="tdna-errors">' +
            '<div class="tdna-errors-title">' + failed.length +
            ' file(s) could not be scored</div><ul>' +
            failed.map(function (f) {
                return '<li><code>' + esc(f.filename) + '</code> — ' + esc(f.error) + '</li>';
            }).join('') + '</ul></div>';
    }

    /* ── results ─────────────────────────────────────────── */

    var TIER_META = {
        gold:   { medal: '🥇', color: '#f5a623', label: 'The Perfect Soul' },
        silver: { medal: '🥈', color: '#8ba4c0', label: 'The Mirror' },
        bronze: { medal: '🥉', color: '#cd7f32', label: 'The Adjacent' }
    };

    function renderResults(results) {
        var host = el('tdnaResults');
        if (!host) return;
        if (!results.length) {
            host.innerHTML = '<div class="tdna-empty">No candidates were scored.</div>';
            return;
        }
        var roleTitle = (state.roles.find(function (r) { return r.id === state.roleId; }) || {}).title || '';

        host.innerHTML = results.map(function (r, i) {
            var meta = TIER_META[r.tier] || TIER_META.bronze;
            var matches = (r.dna_matches || []).map(function (m) {
                return '<span class="tdna-match' + (m.found ? ' found' : '') + '" title="' +
                    esc(m.evidence) + '">' + (m.found ? '✓ ' : '— ') + esc(m.trait) + '</span>';
            }).join('');

            return '<div class="tdna-rank">#' + (i + 1) + ' · ' + esc(meta.label) + '</div>' +
                '<div style="padding:14px;background:rgba(10,20,50,0.7);border:1px solid ' +
                    esc(meta.color) + '33;border-radius:13px;">' +
                    '<div style="display:flex;align-items:center;gap:11px;margin-bottom:9px;">' +
                        '<div style="font-size:22px;">' + meta.medal + '</div>' +
                        '<div style="flex:1;min-width:0;">' +
                            '<div style="font-size:14px;font-weight:700;color:#fff;">' + esc(r.name) + '</div>' +
                            '<div style="font-size:11px;color:rgba(255,255,255,0.4);">' +
                                esc(r.filename || roleTitle) + '</div>' +
                        '</div>' +
                        '<div style="font-size:19px;font-weight:800;color:' + esc(meta.color) + ';">' +
                            r.match_score + '</div>' +
                    '</div>' +
                    '<div style="height:3px;background:rgba(255,255,255,0.07);border-radius:999px;' +
                        'overflow:hidden;margin-bottom:9px;"><div style="height:100%;width:' +
                        r.match_score + '%;background:' + esc(meta.color) + ';"></div></div>' +
                    (matches ? '<div class="tdna-matches">' + matches + '</div>' : '') +
                    '<div style="font-size:12px;color:rgba(200,220,255,0.65);line-height:1.55;' +
                        'margin-top:8px;padding:8px 10px;background:' + esc(meta.color) + '08;' +
                        'border-radius:8px;">' + esc(r.ai_analysis || '') +
                        (r.silent_skill ? ' <em style="color:rgba(255,255,255,0.45);">Silent skill: ' +
                            esc(r.silent_skill) + '.</em>' : '') + '</div>' +
                    '<div class="tdna-fb" data-candidate="' + esc(r.id || '') + '">' +
                        '<button class="good" onclick="tdnaFeedback(this,\'good\')">👍 Good match</button>' +
                        '<button class="bad" onclick="tdnaFeedback(this,\'bad\')">👎 Not a fit</button>' +
                    '</div>' +
                    stageRow(r.id) +
                '</div>';
        }).join('');
    }

    /* ── Results: does the score predict the hire? ─────────
       The whole point of recording outcomes. Suppressed below 5 candidates
       in a band — a hire rate from 3 people is noise, and once it is on a
       screen someone will quote it. */

    window.tdnaShowResults = async function () {
        var host = el('tdnaBody');
        if (!host || !state.roleId) return;
        host.innerHTML = '<div class="tdna-empty">Reading your recorded outcomes…</div>';
        try {
            var s = await api('/api/outcomes/stats?role_id=' + encodeURIComponent(state.roleId));
            renderResultsTab(s);
        } catch (e) {
            host.innerHTML = '<div class="tdna-alert">' + esc(e.message) + '</div>';
        }
    };

    function renderResultsTab(s) {
        var host = el('tdnaBody');
        var bands = s.bands || [];
        var anyData = (s.total_outcomes || 0) > 0;

        var html = '<div class="tdna-row" style="margin-bottom:16px;">' +
            '<button class="tdna-btn tdna-btn--ghost" onclick="TeamDNA.reload()">&larr; Back to Team DNA</button>' +
            '<span class="tdna-counter">' + (s.total_outcomes || 0) + ' outcomes recorded</span>' +
            (s.retention_follow_ups_due
                ? '<span class="tdna-counter" style="background:rgba(245,166,35,.12);border-color:rgba(245,166,35,.3);color:#f5a623;">' +
                  s.retention_follow_ups_due + ' due a 12-month check</span>' : '') +
            '</div>';

        if (!anyData) {
            html += '<div class="tdna-empty" style="padding:34px 20px;">' +
                '<div style="font-size:15px;color:rgba(255,255,255,0.6);margin-bottom:8px;">Nothing recorded yet</div>' +
                'Mark candidates as Interviewed or Hired on their cards.<br />' +
                'Once five land in a score band, you will see whether the scores predict your hires.' +
                '</div>';
            host.innerHTML = html;
            return;
        }

        html += '<div class="tdna-section"><div class="tdna-section-title">' +
                'Does the score predict the hire?</div>';

        html += '<div class="bandlist">' + bands.map(function (b) {
            if (b.insufficient_data) {
                return '<div class="band band--thin">' +
                    '<div class="band__h"><b>' + esc(b.label) + '</b>' +
                    '<span class="band__n">' + b.candidates + ' of ' + b.min_sample + '</span></div>' +
                    '<div class="band__msg">Not enough data yet</div></div>';
            }
            return '<div class="band">' +
                '<div class="band__h"><b>' + esc(b.label) + '</b>' +
                '<span class="band__n">' + b.candidates + ' candidates</span></div>' +
                metric('Reached interview', b.reached_interview, b.candidates, b.reached_interview_pct, '#4d9fff') +
                metric('Hired', b.hired, b.candidates, b.hired_pct, '#00d68f') +
                (b.retention_checked
                    ? metric('Still employed at 12 months', b.still_employed, b.retention_checked,
                             b.still_employed_pct, '#f5a623')
                    : '<div class="band__note">' + esc(b.retention_note || 'No 12-month checks answered yet.') + '</div>') +
                '</div>';
        }).join('') + '</div>';

        html += '<div class="tdna-hint" style="margin-top:14px;">' + esc(s.disclaimer || '') + '</div>';
        html += '</div>';
        host.innerHTML = html;
    }

    function metric(label, num, den, pct, colour) {
        var width = (pct == null ? 0 : Math.max(0, Math.min(100, pct)));
        return '<div class="band__m">' +
            '<div class="band__ml">' + esc(label) + '</div>' +
            '<div class="band__bar"><div class="band__fill" style="width:' + width + '%;background:' + colour + ';"></div></div>' +
            '<div class="band__mv">' + (pct == null ? '—' : pct + '%') +
            '<span>' + num + '/' + den + '</span></div>' +
            '</div>';
    }

    /* ── outcomes: what actually happened ──────────────────
       The score is only half the record. This half is what makes the scoring
       provable later, and it cannot be backfilled — so it is one click on the
       card, not a form behind a modal. */

    var STAGES = [
        { key: 'contacted',   label: 'Contacted' },
        { key: 'screened',    label: 'Screened' },
        { key: 'interviewed', label: 'Interviewed' },
        { key: 'offered',     label: 'Offered' },
        { key: 'hired',       label: 'Hired' },
        { key: 'rejected',    label: 'Rejected' }
    ];

    function stageRow(candidateId) {
        if (!candidateId) return '';
        var opts = '<option value="">Record outcome…</option>' + STAGES.map(function (s) {
            return '<option value="' + s.key + '">' + s.label + '</option>';
        }).join('');
        return '<div class="tdna-stage" data-candidate="' + esc(candidateId) + '">' +
                   '<select onchange="tdnaSetStage(this)" aria-label="Candidate stage">' + opts + '</select>' +
                   '<span class="tdna-stage-state"></span>' +
               '</div>';
    }

    window.tdnaSetStage = async function (sel) {
        var wrap = sel.closest('.tdna-stage');
        var candidateId = wrap && wrap.getAttribute('data-candidate');
        var stage = sel.value;
        var state_el = wrap.querySelector('.tdna-stage-state');
        if (!candidateId || !stage) return;

        // A rejection is only useful later if we know why.
        var reason = null;
        if (stage === 'rejected') {
            reason = prompt('Why not? (optional — this calibrates future scoring)') || null;
        }

        sel.disabled = true;
        state_el.textContent = 'saving…';
        state_el.className = 'tdna-stage-state';
        try {
            var body = await api('/api/outcomes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    role_id: state.roleId, candidate_id: candidateId,
                    stage: stage, rejected_reason: reason
                })
            });
            var o = body.outcome || {};
            state_el.textContent = '✓ ' + stage;
            state_el.className = 'tdna-stage-state is-saved';
            if (o.follow_up_date) {
                state_el.title = '12-month check due ' + o.follow_up_date;
                state_el.textContent += ' · check ' + o.follow_up_date;
            }
            toast('Recorded. This is what makes the scores provable later.', 'success');
        } catch (e) {
            state_el.textContent = 'not saved';
            state_el.className = 'tdna-stage-state is-err';
            toast(e.message, 'error');
        } finally {
            sel.disabled = false;
        }
    };

    /* ── feedback ────────────────────────────────────────── */

    window.tdnaFeedback = async function (btn, verdict) {
        var wrap = btn.closest('.tdna-fb');
        var candidateId = wrap && wrap.getAttribute('data-candidate');
        if (!candidateId) { toast('This result has no saved candidate to rate', 'error'); return; }

        var reason = null;
        if (verdict === 'bad') {
            // The reason is what makes the calibration useful, but never force it.
            reason = prompt('Why not a fit? (optional — this calibrates future scoring)') || null;
        }

        Array.prototype.forEach.call(wrap.querySelectorAll('button'), function (b) {
            b.disabled = true; b.classList.remove('on');
        });
        btn.classList.add('on');

        try {
            await api('/api/candidates/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    role_id: state.roleId,
                    candidate_id: candidateId,
                    verdict: verdict,
                    reason: reason
                })
            });
            toast('Noted — future scoring for this role is calibrated on your verdicts', 'success');
        } catch (e) {
            Array.prototype.forEach.call(wrap.querySelectorAll('button'), function (b) {
                b.disabled = false;
            });
            btn.classList.remove('on');
            toast(e.message, 'error');
        }
    };

    window.TeamDNA = { state: state, reload: loadModel };
})();
