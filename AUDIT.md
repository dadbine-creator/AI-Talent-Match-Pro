# AI Talent Match Pro — Project Audit (Task 0)

**Date:** 2026-08-24
**Scope:** Read-only. No code changed.
**Stack:** FastAPI (`app/main.py`, ~189KB monolith) · SQLite (`elinor.db`) · Azure OpenAI GPT-4o · Stripe · Azure App Service (`aitmp-io`).
**Method:** Static trace of the real code paths (grep + targeted reads) across `main.py`, `db.py`, the `*_engine.py` modules, `workspace.html`, `landing_page.html`, and `static/`.

---

## 0. Executive summary — read this first

**The honest, working pieces exist but are bypassed by the UI. Everything the marketing copy sells is theater.**

- The workspace's only AI call is `POST /api/grade` — **that route does not exist.** The landing-page live demo calls the same nonexistent route.
- Every candidate a user ever sees is one of ~6 **hardcoded JavaScript names** (Sarah Chen, Marcus Williams, Priya Patel, Alex Rivera, Jordan Smith, Taylor Wong). The "AI is thinking" progress and the "sending via LinkedIn / candidate replied YES" flow are `setTimeout` + `Math.random()` animations.
- The two real scoring endpoints (`/api/candidates/search`, `/api/candidates/score`) **throw on every call** because they call `run_full_talent_match()` with a signature that does not match `ai_engine.py`. They return 500/503 100% of the time.
- The one genuinely clean integration — `/api/apollo/search`, which returns an honest 501 when no key is set — **is never called by the UI.**
- Billing is **completely disconnected from signup.** Register hardcodes `plan="free"`, creates no Stripe customer, no subscription, no trial, and there is no subscription gate anywhere. There is no card-required trial today.
- Register **leaks the company's raw API key** in the HTTP response. Session and Stripe-webhook secrets fall back to insecure hardcoded defaults instead of failing hard.

**Bottom line: the core promise (find & score real candidates) is not implemented; the billing model in the brief is not built; and there are two live security leaks.** Details, severities, and fix order below.

---

## 1. User-flow trace (end to end)

Verdicts reflect **actual runtime behavior**, not intent.

| # | Step | Endpoint / code | Verdict |
|---|------|-----------------|---------|
| 1 | Landing → primary CTA | "Start Free Trial" `landing_page.html:361` → `/register` (`main.py:308`) | **WORKS** (goes to register) |
| 1b | Landing → live demo button | "Find My Top 3 Candidates" `landing_page.html:504` → `runDemo()` → `POST /api/grade` `landing_page.html:848` | **BROKEN** — `/api/grade` doesn't exist; falls to `catch` → shows `Math.random()` score |
| 2 | Register submits | `POST /api/company/register` → `register_company` `main.py:406-418` | **WORKS** (but leaks api_key; see B5) |
| 3 | Login | `POST /api/company/login` → `company_login` `main.py:420-429` | **WORKS** |
| 4 | Redirect to workspace | `GET /workspace` `main.py:312`; first paint fetches `/api/me` `workspace.html:1285` | **WORKS** (static skeleton cards only) |
| 5 | Enter job description → search | `p17SearchWithAI()` → `POST /api/grade` `workspace.html:999` | **BROKEN** — route doesn't exist → 404 |
| 6 | Candidate sourcing, no `APOLLO_API_KEY` | `POST /api/apollo/search` → honest `501` `main.py:657-666` | **WORKS but UNREACHABLE** — UI never calls it |
| 7 | Scoring | `POST /api/candidates/score` → `run_full_talent_match(...)` `main.py:604` vs `ai_engine.py:210` | **BROKEN** — signature mismatch → 503 every time; not two-pass |
| 8 | Results render (tiers) | `p17ShowResultsInChat()` `workspace.html:1220-1236` | **NOT BUILT** — hardcoded JS names; API response ignored |
| 9 | AI chat | `POST /api/copilot/run` → `run_copilot_session` `main.py:1564`, `copilot_engine.py:284` | **WORKS (backend) / NOT WIRED** — workspace never calls it |
| 10 | Billing / payment | `register_company` hardcodes `plan="free"`; no Stripe at signup | **NOT BUILT into the flow** |

### Detail on the critical steps

**Step 2 — Register.** `register_company` (`main.py:406-418`) writes a `CompanyORM` row (`companies`: id, name, domain, `plan="free"`, seat_count/limit, `api_key=secrets.token_hex(32)`) and a `CompanyUserORM` row (`company_users`: email, name, bcrypt-hashed password, role="admin"). Password hashing is correct (bcrypt via `passlib`, `main.py:222`). **The JSON response returns the raw `api_key`** (`main.py:418`). Note the brief expects `/api/auth/register`; the actual route is `/api/company/register` (and a separate legacy passwordless `POST /register` at `main.py:379` writes to a different `users` table).

**Step 3 — Login.** Starlette `SessionMiddleware` signed cookie (`main.py:122`). Sets `company_user_id`, `company_id`, `user_role` (`main.py:428`). Secret: `SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "dev-only-secret")` (`main.py:108`) — **insecure default, only `warnings.warn`, no hard fail** → forgeable cookies if unset in prod. Brief expects `/api/auth/login`; actual is `/api/company/login`.

**Step 5 — JD submit.** `p17SearchWithAI()` (`workspace.html:963`) runs 7 fake `setTimeout` "thinking" steps (`:982-997`), then `POST /api/grade` (`:999`). **No `@app.post("/api/grade")` exists** — grep finds it only inside a marketing string at `main.py:2693`. FastAPI returns 404; `res.json()` still parses `{"detail":"Not Found"}`, so the `catch` at `:1011` does NOT fire and the code renders hardcoded defaults.

**Step 7 — Scoring.** `run_full_talent_match` is imported from `ai_engine.py` (`main.py:49`). Actual signature: `run_full_talent_match(role_title, human_story, membership_tier="free") -> List[CandidateResult]` (`ai_engine.py:210`). Callers are wrong:
- `/api/candidates/score` (`main.py:604`) passes the résumé **list** as `membership_tier` (→ `tier_rules[<list>]` `TypeError`), and unpacks two values from a one-list return → caught at `:607` → **503 always**. The uploaded résumés are silently dropped.
- `/api/candidates/search` (`main.py:344-351`) does `return {"ok": True, **result}` where `result` is a list → `TypeError` → caught → **500 always**.
- Legacy `/results` (`main.py:1658`) same unpack failure → **500**.
- It is **not** two-pass. `ai_engine.py` is single-pass and sources candidates from a **hardcoded stub** `search_linkedin_profiles()` (Alex Rivier / Jordan Smith / Taylor Wong, `ai_engine.py:67-92`); GPT only fills tier/score text.

**Step 8 — Results.** `p17ShowResultsInChat(data,...)` (`workspace.html:1220-1228`): Gold = `data.candidate_name || 'Sarah Chen'`, score `|| 87`; Silver ("Marcus Williams") and Bronze ("Priya Patel") fully hardcoded. Because `/api/grade` 404s, the user gets **Sarah Chen / Marcus / Priya every single time.** `p17ShowDemoResultsInChat` and `findMoreCandidates` are more hardcoded trios.

**Step 10 — Billing.** No payment anywhere in signup→workspace. Stripe endpoints exist off to the side (`/api/billing/upgrade` `main.py:486`, `/api/billing/checkout` `main.py:3454`, single webhook `POST /stripe-webhook` `main.py:1623`) but nothing creates a subscription at register, and no route is subscription-gated. **All plans check out at one hardcoded price** `STRIPE_PRICE_ID = "price_1TFDd5JEOljoVrx0eoAVExvJ"` (`main.py:168`); `graph_engine.py:12-13` has placeholder `"price_corporate"`/`"price_enterprise"` that will fail against real Stripe.

---

## 2. Issue register

Severity: **BLOCKER** = core function broken or live security/data leak · **MAJOR** = wrong/misleading behavior, missing model, or exploitable gap · **MINOR** = hygiene / cleanup.

| ID | Sev | Issue | Evidence |
|----|-----|-------|----------|
| B1 | BLOCKER | `POST /api/grade` — the ONLY search call from both the workspace and the landing demo — does not exist. Core "search" never runs. | `workspace.html:999`, `landing_page.html:848`; no route in `main.py` (only string at `:2693`) |
| B2 | BLOCKER | Every candidate shown is hardcoded JS; the API response is ignored. No real candidate is ever displayed. | `workspace.html:1223-1249` |
| B3 | BLOCKER | `POST /api/candidates/search` returns 500 on every call (`{**list}` spread `TypeError`). Unusable + unauthenticated. | `main.py:344-352` |
| B4 | BLOCKER | `POST /api/candidates/score` returns 503 on every call (signature mismatch); silently ignores uploaded résumés; not the claimed two-pass engine. | `main.py:604-608`, `ai_engine.py:210` |
| B5 | BLOCKER | Register returns the company's **raw `api_key`** in the HTTP response (credential leak). | `main.py:418` |
| B6 | BLOCKER | Billing is disconnected from signup: no card, no trial, no subscription, no access gate. The brief's card-required trial is **not built**. | `main.py:406`; no `require_active_subscription` anywhere |
| B7 | BLOCKER | `SESSION_SECRET_KEY` falls back to `"dev-only-secret"` (forgeable session cookies) and `STRIPE_WEBHOOK_SECRET` to a placeholder — both only warn, never fail. | `main.py:108-111, 169` |
| M1 | MAJOR | False UI claims: "searches LinkedIn directly / finds real candidates", "sends via LinkedIn", "monitors replies", "CRM auto-sync" — none implemented (all `setTimeout`/comments). Chargeback + trust risk. | `landing_page.html:340,456,502,525,565`; `workspace.html:889-940,1093-1098` |
| M2 | MAJOR | `POST /api/candidates/search` has **no auth** and is designed to return candidate data — no login, no quota, no rate limit. | `main.py:336` |
| M3 | MAJOR | `GET /api/narrative/acquisition` — no auth, queries `CompanyCandidateORM`/`UsageLogORM` with **no company filter** (cross-tenant leak) and spends money on a GPT call per hit. | `main.py:2723-2730` |
| M4 | MAJOR | The real Apollo integration (honest 501 without key) is never wired into the UI, so users never reach it. | `main.py:657`; no call in `workspace.html` |
| M5 | MAJOR | The copilot backend works and degrades gracefully, but the workspace never calls `/api/copilot/*`. | `main.py:1564`; no ref in `workspace.html` |
| M6 | MAJOR | Frontend swallows all errors and renders fake results, so real failures (404/500/503) are invisible — users get confident wrong data. | `workspace.html:1011-1012` |
| M7 | MAJOR | All plans check out at one hardcoded price; corporate/enterprise price IDs are placeholders that fail against Stripe. | `main.py:168,491`; `graph_engine.py:12-13` |
| M8 | MAJOR | Two parallel identity systems (`CompanyUserORM`/`company_user_id` vs legacy `UserORM`/`user_email`) with two `/me` endpoints and two register flows — ambiguous auth surface. | `main.py:379-401,406-429,3491` |
| M9 | MAJOR | User/company tables lack the columns the trial model needs (`subscription_status`, `trial_end`, `current_period_end` on the active `CompanyUserORM`/`CompanyORM`). A `SubscriptionORM` exists but is never created at signup. | `db.py:71-86,111+,155-168` |
| M10 | MAJOR | Auth is enforced by *calling* `require_*()` in each handler body, not via `Depends`. A forgotten call silently makes a route public (exactly what happened to `/api/candidates/search`). | pattern across `main.py` |
| M11 | MAJOR | `POST /api/dev/playground` — unauthenticated proxy that invokes internal endpoints by name (allowlisted, but still open). | `main.py:2815` |
| M12 | MAJOR | Dead second Stripe webhook implementation (`handle_stripe_webhook`) imported from `graph_engine` but never routed — two implementations, one live. | `main.py:3388`, `graph_engine.py:138` |
| M13 | MAJOR | File-based SQLite (lock-prone) with most DB reads lacking `try/except` → SQLite lock/`OperationalError` surfaces as an unhandled 500. | `main.py:519,720` (examples) |
| m1 | MINOR | Large amount of dead/duplicate/unreferenced files (see §3). | see §3 |
| m2 | MINOR | `FileResponse("app/*.html")` on static pages has no existence check → 500 if a file is renamed/missing (this is how `/dashboard` broke previously). | `main.py:356,359,362,...` |
| m3 | MINOR | Readiness/marketing string advertises `POST /api/grade` as `"ready": true` though it doesn't exist. | `main.py:2693` |
| m4 | MINOR | `signal_engine` fabricates activity via `random.choice`; surfaced by `/api/signals/*`. | `signal_engine.py:321` |
| m5 | MINOR | `POST /api/auth/verify-hr` unauthenticated (low risk; only classifies a job-title string). | `main.py:3272` |
| m6 | MINOR | `STRIPE_PRICE_ID` hardcoded rather than env-sourced. | `main.py:168` |

### Contract note for later tasks (Tasks 2 & 4)
The brief references `/api/auth/register`, `/api/auth/login`, `/api/apollo/search`, `/api/candidates/score`, `/api/copilot/run`. Actual names present:
- `/api/auth/register` → **does not exist**; actual `/api/company/register` (`:406`) + legacy `/register` (`:379`).
- `/api/auth/login` → **does not exist**; actual `/api/company/login` (`:420`).
- `/api/apollo/search` ✓ (`:657`), `/api/candidates/score` ✓ but broken (`:558`), `/api/copilot/run` ✓ (`:1564`), `/api/me` ✓ (`:3491`).

The healthcheck script (Task 2) will need the real names, or we standardize on `/api/auth/*` aliases first.

---

## 3. Codebase map & dead code

**Real entrypoint:** `app/main.py` (FastAPI) — confirmed by `startup.txt` (`uvicorn app.main:app`) and `requirements.txt`. `function_app.py` (+ `azure_function/`, `grade/`) is a separate legacy Azure Functions grader, not the live product.

**Live engine modules imported by main.py:** `db, ai_engine, sla_engine, cost_engine, api_v1_engine, integrations_engine, jd_engine, outreach_engine, copilot_engine, phase24, recruiter_analytics_engine, forecast_engine, forecast_engine_v2, narrative_engine, interview_engine, intelligence_engine, scorecard_engine, signal_engine, coaching_engine, mobile_engine, linkedin_engine, graph_engine`.

**HTML served by a route:** `landing_page, register, login, workspace, job, privacy, terms, accessibility, about, careers, blog, newsroom, plans, api_docs, admin, developer`.

### Dead / duplicate / unreferenced (candidates for cleanup)
- **Duplicates:** `app/main.py.backup`; `requirements_backup.txt`, `requirements_phase20.txt`; `app/static/graph_engine.py` & `app/static/linkedin_engine.py` (stray copies of real engines under `static/`); `azure_function/` (dup of root Functions setup); `app/index.html` (older unused landing).
- **Dead code (never imported):** `app/_api.py`, `app/models.py`, `app/test_engine.py`, `app/fix_main.py`, `app/backend/pycase/linkedin.py`, root `App.js`.
- **HTML with no serving route:** `app/analytics.html`, `app/billing.html`, `app/index.html`, `app/how-it-works.html`. (`dashboard.html` is referenced but doesn't exist — `/dashboard` now redirects to `/workspace`.)
- **JS never included by any page:** `static/gate.js`, `login-modal.js`, `scroll.js`, `theme.js`, `theme-switch.js`, `js/aiStream.js`, `js/candidateEngine.js`; **CSS:** `static/landing.css`.
- **Junk:** `app/static/at-plain.png` (0 bytes); root `....` (0-byte file); `app/frontend/` (empty).
- **Separate project:** `talent-match-frontend/` (independent Vite React app with its own node_modules).

---

## 4. Recommended fix order

Ordered by dependency and risk. Task numbers map to your brief.

1. **Security first — stop the bleeding (Task 1 + B5/B7).**
   Rotate the compromised Azure OpenAI key; remove the `api_key` from the register response (B5); make `SESSION_SECRET_KEY`, `STRIPE_SECRET_KEY`, and `STRIPE_WEBHOOK_SECRET` **fail hard** when unset in prod (B7). Confirm no secret is committed. *(Task 1 is read/report-only per your brief — I'll report the grep + `az` commands, you run them.)*

2. **Fix the AI contract so scoring can work at all (B3/B4).**
   Align `run_full_talent_match`'s signature with its callers; make `/api/candidates/score` actually consume the uploaded résumés and return real tiers + per-criterion evidence; decide single-pass vs. the promised two-pass and implement honestly.

3. **Wire the UI to the real endpoints and kill the fakes (B1/B2/B6-UI/M6).**
   Replace `/api/grade` with the real search/score endpoints; delete the hardcoded candidate arrays; surface real error states instead of silently rendering Sarah Chen.

4. **De-risk Apollo before you pay for it (Task 3) and wire it in (M4).**
   Capture the People Search response schema as a fixture, test `ai_engine.py`'s parsing against it, fix field mismatches — then connect `/api/apollo/search` into the search flow.

5. **Build the card-required 7-day trial (Task 4 / B6 / M7 / M9).**
   Migration for Stripe columns; Checkout Session with `trial_period_days=7`, `payment_method_collection='always'`, `missing_payment_method='cancel'`; one idempotent webhook; a single `require_active_subscription` dependency on every protected route; UI (card notice + first-charge date, trial banner, expired blocking screen).

6. **Consolidate auth & close the open endpoints (M2/M3/M8/M10/M11).**
   Move to FastAPI `Depends` for auth; add auth to `/api/candidates/search`, `/api/narrative/acquisition`, `/api/dev/playground`; add a company filter to the narrative query; unify the two identity systems.

7. **Make the copy true (M1).**
   Align landing/workspace claims with what the code actually does (per your rule, the hero paragraph stays untouched).

8. **Test harness + cleanup (Task 2 / m1-m6).**
   `scripts/healthcheck.py` against the real endpoint names; then remove dead/duplicate files and add existence guards to `FileResponse` routes.

---

*End of audit. No code was modified. Awaiting your review before proceeding to Task 1.*
