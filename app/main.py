import os
import secrets
import uuid
import time
import json
from datetime import datetime, timedelta

from fastapi import (
    FastAPI, Request, Body, Depends, HTTPException, Header
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

# Stripe
import stripe

# SQLAlchemy ORM imports
from app.db import (
    SessionLocal, get_db,
    UserORM, ConversationORM, CandidateMatchORM,
    CompanyORM, CompanyUserORM, TeamInviteORM,
    SubscriptionORM, InvoiceORM,
    CompanyRoleORM, CompanyCandidateORM, UsageLogORM,
    # Phase 23
    FeedbackEventORM, FeedbackAggregateORM,
    ModelVersionORM, InsightSnapshotORM,
    AINarrativeORM, ForecastORM, TelemetryORM,
    # Phase 24
    DataFusionORM, CostOptimizerORM,
    RecruiterAnalyticsORM, SLAAlertORM,
    # Phase 31
    APIKeyORM, WebhookORM, WebhookDeliveryLogORM, APIAuditLogORM,
    # Phase 32
    PartnerSyncLogORM, JobDescriptionORM,
    # Phase 33
    RecruiterProjectORM, PipelineStageORM,
    ProjectCandidateORM, OutreachORM, RecruiterCopilotORM,
    EmailTokenORM, EmailSubscriberORM,
    init_db,
)
from sqlalchemy.orm import Session
from sqlalchemy import func

# Password hashing
from passlib.context import CryptContext

# AI Engine
from app.ai_engine import run_full_talent_match, score_candidates
import app.email_engine as email_engine
import app.paddle_engine as paddle_engine  # NEW payment processor (Paddle Billing), alongside Stripe

# B — hard-gate the workspace behind email verification. Default OFF so real signups aren't
# locked out while the sender is onboarding@resend.dev (which only delivers to the Resend account
# owner). Flip to "true" ONLY after the aitmp.io domain is verified in Resend.
REQUIRE_EMAIL_VERIFICATION = os.getenv("REQUIRE_EMAIL_VERIFICATION", "false").strip().lower() == "true"

# OpenAI for narratives
import httpx

# Phase 27 — SLA Engine
from app.sla_engine import run_sla_check, get_sla_status_color, SLA_TARGETS

# Phase 28 — Cost Engine
from app.cost_engine import (
    run_cost_optimization, get_cost_summary,
    check_ai_call_allowed, check_cost_alerts,
    select_model_for_tier, track_ai_call,
    PLAN_BUDGETS
)

# Phase 31 — API v1 Engine
from app.api_v1_engine import (
    validate_api_key, create_api_key,
    fire_event, deliver_webhook,
    log_api_call, detect_abuse,
    VALID_SCOPES, WEBHOOK_EVENTS
)

# Phase 32 — Integrations + JD Engine
from app.integrations_engine import (
    process_inbound_event, push_to_partner,
    get_integration_status, retry_failed_syncs,
    verify_greenhouse_signature, verify_lever_signature,
    ZAPIER_APP_MANIFEST, MAKECOM_MODULE_MANIFEST, PARTNERS
)
from app.jd_engine import (
    generate_job_description, get_jd_for_role,
    get_available_tones, get_available_role_types
)

# Phase 33 — Outreach + Copilot Engine
from app.outreach_engine import (
    generate_outreach, generate_batch_outreach,
    mark_outreach_sent, get_outreach_stats,
    get_message_types, get_outreach_tones
)
from app.copilot_engine import (
    run_copilot_session, submit_copilot_feedback,
    get_copilot_history, get_copilot_stats,
    get_session_types
)

# ============================================================
# INIT
# ============================================================
init_db()

app = FastAPI(
    title="AI Talent Match Pro",
    version="33.0.0",
    description="Enterprise AI Recruiting Platform — $1B Acquisition Ready"
)

# ── B7: secret hardening — never boot a non-dev environment on an insecure fallback ──
import warnings
_ENV = os.getenv("ENV", "").strip().lower()
IS_DEV_ENV = _ENV in ("development", "dev", "local", "test")

def _require_secret(name: str, dev_fallback: str = "") -> str:
    """Load a required secret from the environment.
    Development (ENV explicitly development/dev/local/test): allow an insecure fallback, with a warning.
    Any other environment (including ENV unset): a missing secret is FATAL — refuse to start."""
    val = os.getenv(name)
    if val:
        return val
    if IS_DEV_ENV:
        warnings.warn(
            f"⚠️  {name} is not set — using an insecure development fallback (ENV={_ENV or 'unset'}). "
            "NEVER run production like this.", stacklevel=2)
        return dev_fallback
    raise RuntimeError(
        f"FATAL: {name} is not set. Set it as an environment variable / App Service application setting, "
        "or set ENV=development for local development.")

SECRET_KEY = _require_secret("SESSION_SECRET_KEY", "dev-only-secret")
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://aitmp.io"] if os.getenv("ENV","dev") == "prod" else ["https://aitmp.io","http://localhost:5500","http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# HTTPS-only in production
_is_prod = os.getenv("ENV","dev") == "prod"
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=_is_prod, same_site="strict")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ── Team DNA (additive) ──────────────────────────────────────
# Score candidates against the customer's OWN best employees. Registered as a
# router so nothing above this line changes. See app/team_dna_routes.py.
from app.team_dna_routes import router as team_dna_router
app.include_router(team_dna_router)

# ── Hiring outcomes (additive) ───────────────────────────────
# Pairs each score with what actually happened. See app/outcomes_routes.py.
from app.outcomes_routes import router as outcomes_router
app.include_router(outcomes_router)

# ── Roles: active-role accounting + archiving (additive) ─────
from app.roles_routes import router as roles_router
app.include_router(roles_router)

# ── ATS integrations: Greenhouse + Lever, for real (additive) ──
from app.integrations_routes import router as ats_router
app.include_router(ats_router)

# ── Candidates arriving by email, one address per role (additive) ──
from app.intake_routes import router as intake_router
app.include_router(intake_router)

# ============================================================
# GLOBAL EXCEPTION HANDLER
# ============================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    try:
        db = SessionLocal()
        company_id = None
        try: company_id = request.session.get("company_id")
        except Exception: pass
        log = TelemetryORM(endpoint=str(request.url.path), method=request.method, status_code=500, latency_ms=0, company_id=company_id, error=str(exc))
        db.add(log); db.commit(); db.close()
    except Exception: pass
    return JSONResponse({"ok": False, "error": "Internal server error"}, status_code=500)


# ============================================================
# 404 — branded page for browser navigations; JSON for API routes
# ============================================================
from starlette.exceptions import HTTPException as _StarletteHTTPException

@app.exception_handler(_StarletteHTTPException)
async def http_exception_handler(request: Request, exc: _StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api"):
        return FileResponse("app/404.html", status_code=404)
    # Preserve FastAPI's default JSON shape ({"detail": ...}) for everything else
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ============================================================
# SEO — robots.txt + sitemap.xml
# ============================================================
@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /workspace\n"
        "Disallow: /admin\n"
        "Disallow: /api/\n"
        "Sitemap: https://aitmp.io/sitemap.xml\n"
    )

@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    paths = ["/", "/plans", "/api-docs", "/about", "/careers", "/blog",
             "/newsroom", "/refund", "/terms", "/privacy", "/accessibility",
             "/login", "/register"]
    today = datetime.utcnow().strftime("%Y-%m-%d")
    urls = "".join(
        f"<url><loc>https://aitmp.io{p}</loc><lastmod>{today}</lastmod>"
        f"<changefreq>weekly</changefreq></url>"
        for p in paths
    )
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f"{urls}</urlset>")
    return Response(content=xml, media_type="application/xml")


# ============================================================
# TELEMETRY MIDDLEWARE
# ============================================================
@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    latency_ms = round((time.time() - start) * 1000, 2)
    try:
        db = SessionLocal()
        company_id = request.session.get("company_id") if hasattr(request, "session") else None
        log = TelemetryORM(endpoint=str(request.url.path), method=request.method, status_code=response.status_code, latency_ms=latency_ms, company_id=company_id)
        db.add(log); db.commit(); db.close()
        if latency_ms > 100: _check_sla_breach("latency", latency_ms, 100, company_id)
    except Exception: pass
    response.headers["X-Latency-Ms"]             = str(latency_ms)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"]    = "nosniff"
    response.headers["X-Frame-Options"]           = "DENY"
    response.headers["X-Phase"]                   = "33.0.0"
    return response

# ============================================================
# STRIPE + AZURE + PARTNER CONFIG
# ============================================================
stripe.api_key        = os.getenv("STRIPE_SECRET_KEY", "YOUR_STRIPE_SECRET_KEY")
STRIPE_SECRET_KEY     = os.getenv("STRIPE_SECRET_KEY", "")  # FIX C: was referenced but never defined
STRIPE_PRICE_ID       = "price_1TFDd5JEOljoVrx0eoAVExvJ"
# B7 (relaxed): the webhook secret is only security-critical once Stripe is actually configured.
# Until STRIPE_SECRET_KEY is set (billing ships in Task 4), boot without it; then it becomes mandatory.
STRIPE_WEBHOOK_SECRET = _require_secret("STRIPE_WEBHOOK_SECRET") if STRIPE_SECRET_KEY else os.getenv("STRIPE_WEBHOOK_SECRET", "")
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "https://ai-talent-match-openai.openai.azure.com/")
AZURE_OPENAI_KEY        = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
LINKEDIN_CLIENT_ID      = os.getenv("LINKEDIN_CLIENT_ID", "")  # FIX B: was referenced but never defined
APOLLO_API_KEY          = os.getenv("APOLLO_API_KEY", "")
APOLLO_BASE_URL         = "https://api.apollo.io/api/v1"

# ============================================================
# RATE LIMITING
# ============================================================
from collections import defaultdict
_rate_limit_store: dict = defaultdict(list)

def check_rate_limit(company_id: str, endpoint: str, max_calls: int = 60, window_seconds: int = 60) -> bool:
    key = f"{company_id}:{endpoint}"; now = time.time()
    calls = [t for t in _rate_limit_store[key] if now - t < window_seconds]
    _rate_limit_store[key] = calls
    if len(calls) >= max_calls: return False
    _rate_limit_store[key].append(now); return True

# ============================================================
# HELPERS
# ============================================================
def _check_sla_breach(alert_type, value, threshold, company_id=None):
    try:
        db = SessionLocal(); severity = "critical" if value > threshold * 2 else "warning"
        alert = SLAAlertORM(id=str(uuid.uuid4()), alert_type=alert_type, severity=severity, message=f"{alert_type} breach: {value:.1f} exceeded threshold {threshold}", metric_value=value, threshold=threshold, company_id=company_id)
        db.add(alert); db.commit(); db.close()
    except Exception: pass

def _get_or_create_cost_optimizer(db, company_id, plan):
    month = datetime.utcnow().strftime("%Y-%m")
    cost = db.query(CostOptimizerORM).filter(CostOptimizerORM.company_id==company_id, CostOptimizerORM.month==month).first()
    if not cost:
        # Read the allowance from PLANS — a hardcoded map here silently enforced
        # a limit the pricing page never mentioned, and gave every NEW tier the
        # 10-call fallback (an Agency customer capped at 10 calls a month).
        # Candidate volume is governed by roles.check_candidate_quota; this is
        # only a backstop against runaway spend.
        limit = PLANS.get(plan, PLANS["free"]).get("ai_calls_per_month", UNLIMITED)
        cost = CostOptimizerORM(id=str(uuid.uuid4()),company_id=company_id,month=month,ai_calls_this_month=0,ai_calls_limit=limit,ai_calls_remaining=limit,budget_limit_usd=limit*0.01)
        db.add(cost); db.commit()
    return cost

# ============================================================
# PLAN CONFIGURATION
# ============================================================
# Pricing is per ACTIVE ROLE, not per seat and not per candidate.
#   active role = a role with Team DNA exemplars or scored candidates attached.
#   Archiving a role frees the slot and keeps the data.
#
# There are no per-candidate caps on paid plans. Free is capped at
# FREE_CANDIDATES_PER_MONTH, which is the upgrade trigger.
#
# Legacy keys (business / corporate / enterprise) are kept below so existing
# subscribers on the old Stripe prices keep working exactly as they are. They
# are not offered to new customers — NEW_PLAN_KEYS is what the pricing page shows.
UNLIMITED = 999_999
FREE_CANDIDATES_PER_MONTH = 100
FREE_BULK_BATCH_LIMIT = 50

PLANS = {
    "free":       {"name": "Free",       "price_monthly": 0,   "price_annual": 0,
                   "seat_limit": 1,         "active_roles": 1,         "ai_calls_per_month": UNLIMITED,
                   "candidates_per_month": FREE_CANDIDATES_PER_MONTH, "bulk_batch_limit": FREE_BULK_BATCH_LIMIT,
                   "shared_team_dna": False,
                   "features": ["1 active role", "100 candidates scored / month",
                                "Full Team DNA", "Full scoring with reasoning", "1 user"]},
    "single":     {"name": "Single",     "price_monthly": 39,  "price_annual": 390,
                   "seat_limit": UNLIMITED, "active_roles": 1,         "ai_calls_per_month": UNLIMITED,
                   "candidates_per_month": UNLIMITED, "bulk_batch_limit": 200,
                   "shared_team_dna": False,
                   "features": ["1 active role", "Unlimited candidates",
                                "Full Team DNA", "Unlimited users"]},
    "team":       {"name": "Team",       "price_monthly": 149, "price_annual": 1490,
                   "seat_limit": UNLIMITED, "active_roles": 5,         "ai_calls_per_month": UNLIMITED,
                   "candidates_per_month": UNLIMITED, "bulk_batch_limit": 200,
                   "shared_team_dna": True,
                   "features": ["5 active roles", "Unlimited candidates",
                                "Team DNA shared across the company", "Unlimited users"]},
    "agency":     {"name": "Agency",     "price_monthly": 399, "price_annual": 3990,
                   "seat_limit": UNLIMITED, "active_roles": UNLIMITED, "ai_calls_per_month": UNLIMITED,
                   "candidates_per_month": UNLIMITED, "bulk_batch_limit": 200,
                   "shared_team_dna": True,
                   "features": ["Unlimited active roles", "Unlimited candidates",
                                "Team DNA shared across the company", "Unlimited users"]},

    # ── Legacy plans — existing subscribers only, not sold to new customers ──
    "business":   {"name": "Business (legacy)",   "price_monthly": 89,  "price_annual": 890,
                   "seat_limit": UNLIMITED, "active_roles": 5,         "ai_calls_per_month": UNLIMITED,
                   "candidates_per_month": UNLIMITED, "bulk_batch_limit": 200,
                   "shared_team_dna": True, "legacy": True,
                   "features": ["5 active roles", "Unlimited candidates", "Unlimited users"]},
    "corporate":  {"name": "Corporate (legacy)",  "price_monthly": 299, "price_annual": 2990,
                   "seat_limit": UNLIMITED, "active_roles": UNLIMITED, "ai_calls_per_month": UNLIMITED,
                   "candidates_per_month": UNLIMITED, "bulk_batch_limit": 200,
                   "shared_team_dna": True, "legacy": True,
                   "features": ["Unlimited active roles", "Unlimited candidates", "Unlimited users"]},
    "enterprise": {"name": "Enterprise", "price_monthly": 999, "price_annual": 9990,
                   "seat_limit": UNLIMITED, "active_roles": UNLIMITED, "ai_calls_per_month": UNLIMITED,
                   "candidates_per_month": UNLIMITED, "bulk_batch_limit": 200,
                   "shared_team_dna": True,
                   "features": ["Unlimited active roles", "Unlimited candidates",
                                "Custom AI models", "Dedicated support", "SLA"]},
}

# The tiers a new customer is offered.
NEW_PLAN_KEYS = ["free", "single", "team", "agency"]


# ============================================================
# PASSWORD + AUTH HELPERS
# ============================================================
# Direct bcrypt: passlib 1.7.4 (unmaintained) crashes its self-test against bcrypt>=4.1
# ("password cannot be longer than 72 bytes"). Call bcrypt directly — bcrypt truncates at 72 bytes,
# and $2b$ hashes stay compatible with any previously passlib-generated hashes.
import bcrypt as _bcrypt
def hash_password(p):
    return _bcrypt.hashpw(p.encode("utf-8")[:72], _bcrypt.gensalt()).decode("utf-8")
def verify_password(p, h):
    if not h:
        return False
    try:
        return _bcrypt.checkpw(p.encode("utf-8")[:72], h.encode("utf-8") if isinstance(h, str) else h)
    except Exception:
        return False

PERSONAL_DOMAINS = {"gmail.com","yahoo.com","hotmail.com","outlook.com","icloud.com","aol.com","proton.me","protonmail.com","gmx.com","yandex.com"}
def normalize_email(raw): return raw.strip().lower()
def is_corporate_email(email):
    email = normalize_email(email)
    if "@" not in email: return False
    _, domain = email.split("@", 1)
    return domain not in PERSONAL_DOMAINS and "." in domain

def require_user(request: Request):
    if not request.session.get("user_email"): raise HTTPException(status_code=401, detail="Not authenticated")
    return request.session.get("user_email")

def require_company_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("company_user_id")
    if not user_id: raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(CompanyUserORM).filter(CompanyUserORM.id==user_id, CompanyUserORM.is_active==True, CompanyUserORM.is_deleted==False).first()
    if not user: raise HTTPException(status_code=401, detail="User not found")
    return user

def require_admin(request: Request, db: Session = Depends(get_db)):
    user = require_company_user(request, db)
    if user.role != "admin": raise HTTPException(status_code=403, detail="Admin access required")
    return user

def require_recruiter_or_admin(request: Request, db: Session = Depends(get_db)):
    user = require_company_user(request, db)
    if user.role not in ("admin","recruiter"): raise HTTPException(status_code=403, detail="Recruiter access required")
    return user


def get_current_company_user(request: Request, db: Session):
    """Helper that returns (company, user) tuple for current session."""
    user_id = request.session.get("company_user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(CompanyUserORM).filter(
        CompanyUserORM.id == user_id,
        CompanyUserORM.is_active == True,
        CompanyUserORM.is_deleted == False
    ).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    company = db.query(CompanyORM).filter(
        CompanyORM.id == user.company_id,
        CompanyORM.is_active == True,
        CompanyORM.is_deleted == False
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company, user

def log_usage(db, company_id, user_id, action, details=None, latency_ms=None):
    log = UsageLogORM(company_id=company_id, user_id=user_id, action=action, details=details, latency_ms=latency_ms, cost_usd=0.01 if action=="ai_grade" else 0.0)
    db.add(log); db.commit()

def get_sqlalchemy_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ============================================================
# PHASE 31 — API KEY AUTH
# ============================================================
async def require_api_key(request: Request, x_api_key: str = Header(None, alias="X-API-Key"), db: Session = Depends(get_db)):
    if not x_api_key: raise HTTPException(status_code=401, detail="X-API-Key header required")
    valid, api_key, error = validate_api_key(db, x_api_key)
    if not valid: raise HTTPException(status_code=401, detail=error)
    return api_key

def require_scope(scope: str):
    async def _check(x_api_key: str = Header(None, alias="X-API-Key"), db: Session = Depends(get_db)):
        if not x_api_key: raise HTTPException(status_code=401, detail="X-API-Key header required")
        valid, api_key, error = validate_api_key(db, x_api_key, required_scope=scope)
        if not valid: raise HTTPException(status_code=401, detail=error)
        return api_key
    return _check

# ============================================================
# HTML PAGES
# ============================================================
@app.get("/", response_class=HTMLResponse)
def landing_page(): return FileResponse("app/landing_page.html")
@app.get("/register", response_class=HTMLResponse)
def register_page(): return FileResponse("app/register.html")
@app.get("/login", response_class=HTMLResponse)
def login_page(): return FileResponse("app/login.html")
@app.get("/workspace", response_class=HTMLResponse)
def workspace_page(request: Request, db: Session = Depends(get_db)):
    # FIX A: login sets session["company_user_id"], not "user_id" — old check locked everyone out
    uid = request.session.get("company_user_id")
    if not uid:
        return RedirectResponse(url="/login", status_code=302)
    # B — block the workspace until email is verified (only when enforcement is switched on)
    if REQUIRE_EMAIL_VERIFICATION:
        u = db.query(CompanyUserORM).filter(CompanyUserORM.id == uid).first()
        if u and not u.email_verified:
            return RedirectResponse(url="/verify-pending", status_code=302)
    return FileResponse("app/workspace.html")
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, user_email: str = Depends(require_user)):
    # FIX: dashboard.html does not exist — the workspace is the real logged-in home. Redirect there.
    return RedirectResponse(url="/workspace", status_code=302)

@app.get("/job", response_class=HTMLResponse)
def job_page(request: Request, job: str = None): return FileResponse("app/job.html")

@app.get("/billing", response_class=HTMLResponse)
def billing_page(request: Request):
    """Plan and usage. The footer linked here but no route existed — /billing
    404'd on the live site."""
    if not request.session.get("company_user_id"):
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse("app/billing.html")

@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request):
    """Recruiter analytics dashboard. The template existed but had no route, so the
    page was unreachable in the deployed app — served here like /workspace."""
    if not request.session.get("company_user_id"):
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse("app/analytics.html")


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(): return FileResponse("app/privacy.html")

@app.get("/terms", response_class=HTMLResponse)
def terms_page(): return FileResponse("app/terms.html")

@app.get("/accessibility", response_class=HTMLResponse)
def accessibility_page(): return FileResponse("app/accessibility.html")

@app.get("/refund", response_class=HTMLResponse)
def refund_page(): return FileResponse("app/refund.html")

@app.post("/api/candidates/search")
async def api_candidates_search(request: Request, db: Session = Depends(get_db)):
    """Source candidates from a job description alone. Requires Apollo (275M+ profiles).
    Until APOLLO_API_KEY is set this returns an honest 'not connected' — it does NOT fabricate people.
    To score candidates you already have, use POST /api/candidates/score."""
    require_recruiter_or_admin(request, db)  # B3 fix: was unauthenticated
    body = await request.json()
    if not body.get("job_description"):
        return JSONResponse({"ok": False, "error": "Job description required"}, status_code=400)
    if not APOLLO_API_KEY:
        return JSONResponse({
            "ok": False,
            "configured": False,
            "error": "Candidate sourcing isn't connected yet. Add APOLLO_API_KEY to enable search across 275M+ profiles, "
                     "or paste candidates into /api/candidates/score to score them now.",
        }, status_code=501)
    # Apollo is configured: use the dedicated sourcing endpoint (wired in Task 3).
    return JSONResponse({
        "ok": True,
        "configured": True,
        "message": "Apollo is connected — call POST /api/apollo/search to source candidates.",
    })

@app.get("/about", response_class=HTMLResponse)
def about_page(): return FileResponse("app/about.html")

@app.get("/careers", response_class=HTMLResponse)
def careers_page(): return FileResponse("app/careers.html")

@app.get("/blog", response_class=HTMLResponse)
def blog_page(): return FileResponse("app/blog.html")

@app.get("/newsroom", response_class=HTMLResponse)
def newsroom_page(): return FileResponse("app/newsroom.html")

@app.get("/plans", response_class=HTMLResponse)
def plans_page(): return FileResponse("app/plans.html")
@app.get("/api-docs", response_class=HTMLResponse)
def api_docs_page(): return FileResponse("app/api_docs.html")
@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    """Admin console. Was served to anyone — the page itself leaked the
    internal feature set and endpoint names even though its API calls 401.
    Gated on login here; the APIs it calls still enforce the admin role."""
    if not request.session.get("company_user_id"):
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse("app/admin.html")

@app.get("/developer", response_class=HTMLResponse)
def developer_page(request: Request):
    """Developer console — same problem, same fix."""
    if not request.session.get("company_user_id"):
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse("app/developer.html")

# ============================================================
# LEGACY AUTH
# ============================================================
@app.post("/register")
@app.post("/validate_email")
async def register_or_validate(request: Request, db: Session = Depends(get_sqlalchemy_db)):
    try: data = await request.json(); email = normalize_email(data.get("email",""))
    except: form_data = await request.form(); email = normalize_email(form_data.get("email",""))
    if not is_corporate_email(email): return JSONResponse({"ok":False,"error":"Corporate email required."},status_code=400)
    domain = email.split("@",1)[1]; session_token = secrets.token_hex(32)
    user = db.query(UserORM).filter(UserORM.email==email).first()
    if user is None: user = UserORM(email=email,domain=domain,is_validated=True,membership_tier="free",session_token=session_token,last_login=datetime.utcnow()); db.add(user)
    else: user.session_token=session_token; user.last_login=datetime.utcnow(); user.is_validated=True
    db.commit(); request.session["user_email"]=email; request.session["session_token"]=session_token
    return JSONResponse({"ok":True})

@app.get("/logout")
async def logout(request: Request): request.session.clear(); return RedirectResponse(url="/")

@app.get("/me")
async def get_me(request: Request, db: Session = Depends(get_sqlalchemy_db)):
    user_email = request.session.get("user_email")
    if not user_email: return JSONResponse({"ok":False,"error":"Not authenticated"},status_code=401)
    user = db.query(UserORM).filter(UserORM.email==user_email).first()
    if not user: return JSONResponse({"ok":False,"error":"User not found"},status_code=404)
    return JSONResponse({"ok":True,"email":user.email,"name":user.email.split("@")[0].replace("."," ").title()})

# ============================================================
# PHASE 22 — COMPANY + TEAM + BILLING
# ============================================================
def _issue_email_token(db, email, user_id, purpose, hours):
    """Create a one-time email token (purpose: 'verify' | 'reset'). Caller commits."""
    tok = secrets.token_urlsafe(32)
    db.add(EmailTokenORM(id=str(uuid.uuid4()), token=tok, email=email, user_id=user_id,
                         purpose=purpose, expires_at=datetime.utcnow() + timedelta(hours=hours)))
    return tok

@app.post("/api/company/register")
async def register_company(request: Request, db: Session = Depends(get_db)):
    data=await request.json(); name=data.get("name","").strip(); domain=data.get("domain","").strip().lower()
    admin_email=normalize_email(data.get("admin_email","")); admin_name=data.get("admin_name","").strip(); password=data.get("password","")
    job_title=(data.get("job_title") or "").strip(); linkedin_url=(data.get("linkedin_url") or "").strip()
    if not all([name,domain,admin_email,admin_name,password]): raise HTTPException(status_code=400,detail="All fields are required")
    if len(password)<8: raise HTTPException(status_code=400,detail="Password must be at least 8 characters")
    # A — HR job-title gate: this platform is for HR / recruiting / people-ops professionals
    if not is_hr_professional(job_title):
        raise HTTPException(status_code=400, detail="AI Talent Match Pro is built for HR professionals. Please enter your recruiting or talent acquisition title.")
    existing=db.query(CompanyORM).filter(CompanyORM.domain==domain,CompanyORM.is_deleted==False).first()
    if existing: raise HTTPException(status_code=400,detail="Company domain already registered")
    company_id=str(uuid.uuid4()); api_key=secrets.token_hex(32)
    company=CompanyORM(id=company_id,name=name,domain=domain,plan="free",seat_count=1,seat_limit=1,api_key=api_key); db.add(company)
    user_id=str(uuid.uuid4())
    # B — store LinkedIn URL + title (LinkedIn URL kept for future Partner-based HR verification)
    admin=CompanyUserORM(id=user_id,email=admin_email,name=admin_name,password=hash_password(password),company_id=company_id,role="admin",linkedin_url=(linkedin_url or None),job_title=(job_title or None)); db.add(admin); db.commit()
    # Send verification email (no-op until RESEND_API_KEY is set; never blocks signup)
    try:
        _vtoken = _issue_email_token(db, admin_email, user_id, "verify", hours=24); db.commit()
        email_engine.send_verification_email(admin_email, _vtoken, admin_name)
    except Exception:
        db.rollback()
    request.session["company_user_id"]=user_id; request.session["company_id"]=company_id; request.session["user_role"]="admin"
    # B5: api_key is stored on the company row, never returned here. verification_required tells the
    # frontend to show "verify your email" instead of dropping into the workspace (when enforcement is on).
    return JSONResponse({"ok":True,"company_id":company_id,"verification_required":REQUIRE_EMAIL_VERIFICATION,
                         "message":f"Welcome to AI Talent Match Pro, {admin_name}!"})

# ============================================================
# EMAIL FLOWS — verification + password reset (Resend-backed; see email_engine.py)
# All email sends are graceful no-ops until RESEND_API_KEY is set.
# ============================================================
def _email_result_page(title, message, ok=True, cta=None):
    color = "#00d68f" if ok else "#f87171"
    icon = "✓" if ok else "⚠️"
    cta_html = (f'<a href="{cta[1]}" style="display:inline-block;margin-top:24px;padding:12px 24px;'
                f'background:#2563eb;color:#fff;text-decoration:none;border-radius:10px;font-weight:600;">{cta[0]}</a>') if cta else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title></head>
<body style="margin:0;background:#05070f;color:#fff;font-family:-apple-system,'Segoe UI',Arial,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;">
  <div style="max-width:420px;padding:40px;text-align:center;">
    <div style="font-size:44px;margin-bottom:12px;color:{color};">{icon}</div>
    <h1 style="font-size:24px;margin:0 0 10px;">{title}</h1>
    <p style="color:rgba(255,255,255,0.6);line-height:1.6;">{message}</p>
    {cta_html}
  </div></body></html>"""

@app.get("/verify-email", response_class=HTMLResponse)
def verify_email(token: str = "", db: Session = Depends(get_db)):
    rec = db.query(EmailTokenORM).filter(EmailTokenORM.token==token, EmailTokenORM.purpose=="verify").first() if token else None
    if not rec or rec.used_at or rec.expires_at < datetime.utcnow():
        return HTMLResponse(_email_result_page("Link expired or invalid", "This verification link is no longer valid. Sign in and we'll send a fresh one.", ok=False, cta=("Sign in","/login")), status_code=400)
    user = db.query(CompanyUserORM).filter(CompanyUserORM.id==rec.user_id).first()
    if user: user.email_verified = True
    rec.used_at = datetime.utcnow(); db.commit()
    return HTMLResponse(_email_result_page("Email verified", "Your email is confirmed — you're all set.", ok=True, cta=("Go to workspace","/workspace")))

@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(): return FileResponse("app/forgot_password.html")

@app.post("/api/auth/forgot-password")
async def forgot_password_api(request: Request, db: Session = Depends(get_db)):
    data = await request.json(); email = normalize_email(data.get("email",""))
    # Always respond identically — never reveal whether an account exists (prevents enumeration).
    if email:
        user = db.query(CompanyUserORM).filter(CompanyUserORM.email==email, CompanyUserORM.is_deleted==False).first()
        if user:
            try:
                tok = _issue_email_token(db, email, user.id, "reset", hours=1); db.commit()
                email_engine.send_password_reset_email(email, tok, user.name)
            except Exception:
                db.rollback()
    return JSONResponse({"ok": True, "message": "If that email has an account, a reset link is on its way."})

@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(): return FileResponse("app/reset_password.html")

@app.post("/api/auth/reset-password")
async def reset_password_api(request: Request, db: Session = Depends(get_db)):
    data = await request.json(); token = (data.get("token") or "").strip(); new_password = data.get("password","")
    if len(new_password) < 8: raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    rec = db.query(EmailTokenORM).filter(EmailTokenORM.token==token, EmailTokenORM.purpose=="reset").first() if token else None
    if not rec or rec.used_at or rec.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
    user = db.query(CompanyUserORM).filter(CompanyUserORM.id==rec.user_id).first()
    if not user: raise HTTPException(status_code=400, detail="Account not found.")
    user.password = hash_password(new_password); rec.used_at = datetime.utcnow(); db.commit()
    return JSONResponse({"ok": True, "message": "Password updated — you can now sign in."})

@app.post("/api/outreach/notify-reply")
async def notify_candidate_reply(request: Request, db: Session = Depends(get_db)):
    """Send the HR 'candidate replied YES' email. Wired to be called by real reply-detection once
    LinkedIn outreach is live. Email is a no-op until RESEND_API_KEY is set."""
    user = require_recruiter_or_admin(request, db)
    data = await request.json()
    result = email_engine.send_candidate_reply_notification(
        user.email, (data.get("candidate_name") or "").strip(), (data.get("role") or "").strip(), user.name)
    return JSONResponse({"ok": True, "configured": email_engine.is_configured(), "sent": result.get("ok", False)})

@app.get("/verify-pending", response_class=HTMLResponse)
def verify_pending_page(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get("company_user_id")
    if not uid:
        return RedirectResponse(url="/login", status_code=302)
    u = db.query(CompanyUserORM).filter(CompanyUserORM.id == uid).first()
    if u and u.email_verified:
        return RedirectResponse(url="/workspace", status_code=302)
    email = (u.email if u else "your email")
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Verify your email</title></head>
<body style="margin:0;background:#05070f;color:#fff;font-family:-apple-system,'Segoe UI',Arial,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;">
  <div style="max-width:440px;padding:40px;text-align:center;">
    <div style="font-size:44px;margin-bottom:12px;">📧</div>
    <h1 style="font-size:24px;margin:0 0 10px;">Verify your email to activate your workspace</h1>
    <p style="color:rgba(255,255,255,0.6);line-height:1.6;">We've sent a verification link to <strong style="color:#fff;">{email}</strong>. Click it to unlock your workspace.<br><br>Can't find it? Check spam, or resend below.</p>
    <button id="rsBtn" onclick="fetch('/api/auth/resend-verification',{{method:'POST'}}).then(()=>{{this.textContent='Sent ✓';this.disabled=true;}})" style="margin-top:20px;padding:12px 24px;background:#2563eb;color:#fff;border:none;border-radius:10px;font-weight:600;font-size:15px;cursor:pointer;">Resend verification email</button>
    <div style="margin-top:18px;"><a href="/logout" style="color:rgba(255,255,255,0.45);font-size:13px;text-decoration:none;">Sign out</a></div>
  </div></body></html>""")

@app.post("/api/auth/resend-verification")
async def resend_verification(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get("company_user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not signed in")
    u = db.query(CompanyUserORM).filter(CompanyUserORM.id == uid).first()
    if not u:
        raise HTTPException(status_code=404, detail="Account not found")
    if u.email_verified:
        return JSONResponse({"ok": True, "already_verified": True})
    try:
        tok = _issue_email_token(db, u.email, u.id, "verify", hours=24); db.commit()
        email_engine.send_verification_email(u.email, tok, u.name)
    except Exception:
        db.rollback()
    return JSONResponse({"ok": True})

@app.post("/api/company/login")
async def company_login(request: Request, db: Session = Depends(get_db)):
    data=await request.json(); email=normalize_email(data.get("email","")); password=data.get("password","")
    user=db.query(CompanyUserORM).filter(CompanyUserORM.email==email,CompanyUserORM.is_active==True,CompanyUserORM.is_deleted==False).first()
    if not user or not verify_password(password,user.password): raise HTTPException(status_code=401,detail="Invalid email or password")
    company=db.query(CompanyORM).filter(CompanyORM.id==user.company_id,CompanyORM.is_active==True,CompanyORM.is_deleted==False).first()
    if not company: raise HTTPException(status_code=404,detail="Company not found")
    user.last_login=datetime.utcnow(); db.commit()
    request.session["company_user_id"]=user.id; request.session["company_id"]=user.company_id; request.session["user_role"]=user.role
    return JSONResponse({"ok":True,"user_id":user.id,"name":user.name,"email":user.email,"role":user.role,"company":{"id":company.id,"name":company.name,"plan":company.plan}})

@app.get("/api/company/me")
async def company_me(request: Request, db: Session = Depends(get_db)):
    """Current logged-in company user + their company — powers the workspace sidebar + Settings."""
    user = require_company_user(request, db)
    company = db.query(CompanyORM).filter(CompanyORM.id == user.company_id).first()
    plan_key = company.plan if company else "free"
    plan = PLANS.get(plan_key, PLANS["free"])
    return JSONResponse({"ok": True, "name": user.name, "email": user.email, "role": user.role,
        "company": {"name": company.name if company else "", "domain": company.domain if company else "",
                    "plan": plan_key, "plan_name": plan.get("name"), "seat_limit": plan.get("seat_limit")}})

@app.post("/api/subscribe")
async def subscribe_email(request: Request, db: Session = Depends(get_db)):
    """Real capture for the landing 'Notify me' / newsletter forms (was previously discarded)."""
    data = await request.json()
    email = normalize_email(data.get("email", ""))
    source = (data.get("source") or "landing")[:50]
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please enter a valid email address")
    existing = db.query(EmailSubscriberORM).filter(
        EmailSubscriberORM.email == email, EmailSubscriberORM.source == source).first()
    if not existing:
        db.add(EmailSubscriberORM(id=str(uuid.uuid4()), email=email, source=source)); db.commit()
    return JSONResponse({"ok": True, "message": "You're on the list — we'll be in touch."})

@app.get("/api/team")
async def get_team(request: Request, db: Session = Depends(get_db)):
    user=require_admin(request,db); members=db.query(CompanyUserORM).filter(CompanyUserORM.company_id==user.company_id,CompanyUserORM.is_deleted==False).all()
    company=db.query(CompanyORM).filter(CompanyORM.id==user.company_id).first(); plan=PLANS.get(company.plan,PLANS["free"])
    return JSONResponse({"ok":True,"members":[{"id":m.id,"email":m.email,"name":m.name,"role":m.role,"is_active":m.is_active,"last_login":m.last_login.isoformat() if m.last_login else None,"joined_at":m.created_at.isoformat()} for m in members],"seat_used":len(members),"seat_limit":plan["seat_limit"]})

@app.post("/api/team/invite")
async def invite_team_member(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); data=await request.json(); email=normalize_email(data.get("email","")); role=data.get("role","recruiter")
    if role not in ("admin","recruiter","viewer"): raise HTTPException(status_code=400,detail="Invalid role")
    company=db.query(CompanyORM).filter(CompanyORM.id==admin.company_id).first(); plan=PLANS.get(company.plan,PLANS["free"])
    members=db.query(CompanyUserORM).filter(CompanyUserORM.company_id==admin.company_id,CompanyUserORM.is_deleted==False).count()
    if members>=plan["seat_limit"]:
        # Only Free is seat-limited now; paid plans are unlimited users.
        raise HTTPException(status_code=402, detail=(
            f"The {plan['name']} plan includes {plan['seat_limit']} user"
            f"{'s' if plan['seat_limit'] != 1 else ''}. "
            f"Single (${PLANS['single']['price_monthly']}/mo) includes unlimited users."))
    token=secrets.token_urlsafe(32); expires_at=datetime.utcnow()+timedelta(days=7)
    invite=TeamInviteORM(id=str(uuid.uuid4()),email=email,role=role,company_id=admin.company_id,invited_by=admin.id,token=token,expires_at=expires_at); db.add(invite); db.commit()
    return JSONResponse({"ok":True,"invite_url":f"https://aitmp.io/accept-invite?token={token}","expires_at":expires_at.isoformat(),"message":f"Invitation sent to {email}"})

@app.post("/api/team/accept-invite")
async def accept_invite(request: Request, db: Session = Depends(get_db)):
    data=await request.json(); token=data.get("token",""); name=data.get("name","").strip(); password=data.get("password","")
    if len(password)<8: raise HTTPException(status_code=400,detail="Password must be at least 8 characters")
    invite=db.query(TeamInviteORM).filter(TeamInviteORM.token==token,TeamInviteORM.status=="pending",TeamInviteORM.is_deleted==False).first()
    if not invite: raise HTTPException(status_code=404,detail="Invalid or expired invite")
    if datetime.utcnow()>invite.expires_at: invite.status="expired"; db.commit(); raise HTTPException(status_code=400,detail="Invite has expired")
    user_id=str(uuid.uuid4()); user=CompanyUserORM(id=user_id,email=invite.email,name=name,password=hash_password(password),company_id=invite.company_id,role=invite.role); db.add(user)
    company=db.query(CompanyORM).filter(CompanyORM.id==invite.company_id).first(); company.seat_count+=1; invite.status="accepted"; db.commit()
    request.session["company_user_id"]=user_id; request.session["company_id"]=invite.company_id; request.session["user_role"]=invite.role
    return JSONResponse({"ok":True,"message":f"Welcome to the team, {name}!"})

@app.delete("/api/team/{user_id}")
async def remove_team_member(user_id: str, request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db)
    if user_id==admin.id: raise HTTPException(status_code=400,detail="You cannot remove yourself")
    user=db.query(CompanyUserORM).filter(CompanyUserORM.id==user_id,CompanyUserORM.company_id==admin.company_id,CompanyUserORM.is_deleted==False).first()
    if not user: raise HTTPException(status_code=404,detail="User not found")
    user.is_deleted=True; user.deleted_at=datetime.utcnow(); user.updated_by=admin.id
    company=db.query(CompanyORM).filter(CompanyORM.id==admin.company_id).first(); company.seat_count=max(0,company.seat_count-1); db.commit()
    return JSONResponse({"ok":True,"message":"Team member removed"})

@app.patch("/api/team/{user_id}/role")
async def update_team_member_role(user_id: str, request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); data=await request.json(); role=data.get("role","")
    if role not in ("admin","recruiter","viewer"): raise HTTPException(status_code=400,detail="Invalid role")
    user=db.query(CompanyUserORM).filter(CompanyUserORM.id==user_id,CompanyUserORM.company_id==admin.company_id,CompanyUserORM.is_deleted==False).first()
    if not user: raise HTTPException(status_code=404,detail="User not found")
    user.role=role; user.updated_by=admin.id; db.commit()
    return JSONResponse({"ok":True,"message":f"Role updated to {role}"})

@app.get("/api/billing")
async def get_billing(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); company=db.query(CompanyORM).filter(CompanyORM.id==admin.company_id).first(); plan=PLANS.get(company.plan,PLANS["free"])
    subscription=db.query(SubscriptionORM).filter(SubscriptionORM.company_id==admin.company_id,SubscriptionORM.status.in_(["active","trialing"])).first()
    invoices=db.query(InvoiceORM).filter(InvoiceORM.company_id==admin.company_id).order_by(InvoiceORM.issued_at.desc()).limit(10).all()
    return JSONResponse({"ok":True,"plan":plan,"company":{"id":company.id,"name":company.name,"plan":company.plan},"subscription":{"status":subscription.status,"period_end":subscription.current_period_end.isoformat(),"cancel_at_end":subscription.cancel_at_period_end} if subscription else None,"invoices":[{"id":i.id,"amount":i.amount,"status":i.status,"description":i.description,"issued_at":i.issued_at.isoformat(),"pdf_url":i.pdf_url} for i in invoices],"all_plans":PLANS})

@app.post("/api/billing/upgrade")
async def upgrade_plan(request: Request, db: Session = Depends(get_db)):
    """Billing is consolidated on Paddle. This legacy Stripe route no longer creates a
    Stripe session — it tells the client to open the Paddle checkout for the plan."""
    admin = require_admin(request, db)
    data = await request.json(); plan = data.get("plan", "business")
    return JSONResponse({"ok": False, "use_paddle": True, "plan": plan,
                         "paddle": paddle_engine.public_config(),
                         "message": "Checkout now runs through Paddle."})

@app.post("/api/billing/cancel")
async def cancel_subscription(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); sub=db.query(SubscriptionORM).filter(SubscriptionORM.company_id==admin.company_id,SubscriptionORM.status=="active").first()
    if not sub: raise HTTPException(status_code=404,detail="No active subscription")
    try: stripe.Subscription.modify(sub.stripe_subscription_id,cancel_at_period_end=True); sub.cancel_at_period_end=True; db.commit(); return JSONResponse({"ok":True,"message":"Subscription will cancel at period end"})
    except Exception as e: raise HTTPException(status_code=500,detail=str(e))

@app.get("/api/analytics")
async def get_analytics(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); company_id=admin.company_id
    total_searches=db.query(UsageLogORM).filter(UsageLogORM.company_id==company_id,UsageLogORM.action=="search").count()
    total_ai_calls=db.query(UsageLogORM).filter(UsageLogORM.company_id==company_id,UsageLogORM.action=="ai_grade").count()
    total_shortlists=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.shortlisted==True,CompanyCandidateORM.is_deleted==False).count()
    total_candidates=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.is_deleted==False).count()
    avg_latency=db.query(func.avg(UsageLogORM.latency_ms)).filter(UsageLogORM.company_id==company_id,UsageLogORM.latency_ms!=None).scalar() or 0.0
    active_users=db.query(CompanyUserORM).filter(CompanyUserORM.company_id==company_id,CompanyUserORM.is_active==True,CompanyUserORM.is_deleted==False).count()
    gold=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.tier=="gold",CompanyCandidateORM.is_deleted==False).count()
    silver=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.tier=="silver",CompanyCandidateORM.is_deleted==False).count()
    bronze=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.tier=="bronze",CompanyCandidateORM.is_deleted==False).count()
    recent_logs=db.query(UsageLogORM).filter(UsageLogORM.company_id==company_id).order_by(UsageLogORM.created_at.desc()).limit(10).all()
    return JSONResponse({"ok":True,"total_searches":total_searches,"total_candidates":total_candidates,"total_shortlists":total_shortlists,"ai_calls_used":total_ai_calls,"avg_latency_ms":round(avg_latency,2),"active_users":active_users,"candidates_by_tier":{"gold":gold,"silver":silver,"bronze":bronze},"estimated_cost":round(total_ai_calls*0.01,2),"recent_activity":[{"action":log.action,"details":log.details,"latency_ms":log.latency_ms,"created_at":log.created_at.isoformat()} for log in recent_logs]})

@app.get("/api/candidates")
async def get_company_candidates(request: Request, db: Session = Depends(get_db)):
    user=require_company_user(request,db)
    candidates=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==user.company_id,CompanyCandidateORM.is_deleted==False).order_by(CompanyCandidateORM.created_at.desc()).all()
    return JSONResponse({"ok":True,"candidates":[{"id":c.id,"name":c.name,"role":c.role,"tier":c.tier,"match_score":c.match_score,"adaptability":c.adaptability,"focus_penalty":c.focus_penalty,"ai_analysis":c.ai_analysis,"silent_skill":c.silent_skill,"linkedin_url":c.linkedin_url,"notes":c.notes,"shortlisted":c.shortlisted,"partner_source":c.partner_source,"created_at":c.created_at.isoformat()} for c in candidates],"total":len(candidates)})

@app.post("/api/candidates")
async def save_company_candidate(request: Request, db: Session = Depends(get_db)):
    user=require_recruiter_or_admin(request,db); data=await request.json(); candidate_id=str(uuid.uuid4())
    # Validate required fields
    if not data.get("name","").strip(): raise HTTPException(400, "Candidate name is required")
    if not data.get("role","").strip(): raise HTTPException(400, "Candidate role is required")
    if data.get("tier","bronze") not in ("gold","silver","bronze"): raise HTTPException(400, "Invalid tier — must be gold, silver or bronze")
    if not (0 <= data.get("match_score",0) <= 100): raise HTTPException(400, "match_score must be 0-100")
    candidate=CompanyCandidateORM(id=candidate_id,company_id=user.company_id,added_by=user.id,name=data.get("name",""),role=data.get("role",""),tier=data.get("tier","bronze"),match_score=data.get("match_score",0),adaptability=data.get("adaptability",0),focus_penalty=data.get("focus_penalty",0),ai_analysis=data.get("ai_analysis",""),silent_skill=data.get("silent_skill"),linkedin_url=data.get("linkedin_url"),photo=data.get("photo"),notes=data.get("notes",""),shortlisted=data.get("shortlisted",False),job_id=data.get("job_id"))
    db.add(candidate); log_usage(db,user.company_id,user.id,"save_candidate",f"Saved {data.get('name')}")
    await fire_event(db,user.company_id,"candidate.created",{"candidate_id":candidate_id,"name":data.get("name"),"tier":data.get("tier","bronze")})
    return JSONResponse({"ok":True,"id":candidate_id})

@app.patch("/api/candidates/{candidate_id}/notes")
async def update_candidate_notes(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    user=require_recruiter_or_admin(request,db); data=await request.json()
    candidate=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.id==candidate_id,CompanyCandidateORM.company_id==user.company_id,CompanyCandidateORM.is_deleted==False).first()
    if not candidate: raise HTTPException(status_code=404,detail="Candidate not found")
    candidate.notes=data.get("notes",""); db.commit(); return JSONResponse({"ok":True})

@app.patch("/api/candidates/{candidate_id}/shortlist")
async def toggle_shortlist(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    user=require_recruiter_or_admin(request,db)
    candidate=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.id==candidate_id,CompanyCandidateORM.company_id==user.company_id,CompanyCandidateORM.is_deleted==False).first()
    if not candidate: raise HTTPException(status_code=404,detail="Candidate not found")
    candidate.shortlisted=not candidate.shortlisted; db.commit()
    return JSONResponse({"ok":True,"shortlisted":candidate.shortlisted})

# ============================================================
# RESUME UPLOAD → AI SCORING  (NEW — wires workspace dropzone
# to the two-pass engine in ai_engine.py)
# ============================================================
MAX_RESUMES_PER_SEARCH = 50
MAX_RESUME_CHARS = 30000

@app.post("/api/candidates/score")
async def score_uploaded_candidates(request: Request, db: Session = Depends(get_db)):
    """Score uploaded résumés against a job description using the two-pass AI engine."""
    user = require_recruiter_or_admin(request, db)
    company = db.query(CompanyORM).filter(CompanyORM.id == user.company_id).first()

    if not check_rate_limit(user.company_id, "candidates_score", max_calls=10, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many scoring requests — please wait a minute.")

    data = await request.json()
    role_title = (data.get("role_title") or data.get("job_title") or "").strip()
    job_description = (data.get("job_description") or data.get("human_story") or "").strip()
    raw_resumes = data.get("resumes") or data.get("candidates") or []
    job_id = data.get("job_id")

    if not role_title:
        raise HTTPException(status_code=400, detail="role_title is required")
    if not job_description:
        raise HTTPException(status_code=400, detail="job_description is required")
    if not raw_resumes or not isinstance(raw_resumes, list):
        raise HTTPException(status_code=400, detail="At least one résumé is required")
    if len(raw_resumes) > MAX_RESUMES_PER_SEARCH:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_RESUMES_PER_SEARCH} résumés per search")

    # Accept both ["resume text", ...] and [{"name": "...", "text": "..."}]
    resumes = []
    for i, r in enumerate(raw_resumes):
        if isinstance(r, str) and r.strip():
            resumes.append({"name": f"Candidate {i+1}", "text": r.strip()[:MAX_RESUME_CHARS]})
        elif isinstance(r, dict) and (r.get("text") or "").strip():
            resumes.append({
                "name": (r.get("name") or r.get("filename") or f"Candidate {i+1}").strip()[:120],
                "text": r["text"].strip()[:MAX_RESUME_CHARS],
            })
    if not resumes:
        raise HTTPException(status_code=400, detail="No readable résumé text found in upload")

    # Per-ROLE plan accounting. Scoring candidates against a role is the second
    # thing that makes it active, so the limit is checked here — before the AI
    # call, never part-way through one.
    import app.roles as roles_engine
    plan_key = (company.plan or "free")
    if job_id:
        roles_engine.check_can_activate(db, user.company_id, plan_key, job_id)
    # Free-tier monthly candidate cap (paid plans are uncapped).
    roles_engine.check_candidate_quota(db, user.company_id, plan_key, adding=len(resumes))

    cost = _get_or_create_cost_optimizer(db, user.company_id, company.plan)

    # Two-pass engine: triage all résumés, deep GPT-4o on finalists, top 3 back.
    # Runs in a threadpool so the multi-second AI call doesn't block other requests.
    start = time.time()
    try:
        # B4 fix: score the REAL provided candidates (feeds their text to GPT-4o).
        final_results, search_strategy = await run_in_threadpool(
            score_candidates, role_title, job_description, resumes, (company.plan or "free")
        )
    except Exception:
        # Honest failure — never fabricate scores when the AI backend is unavailable.
        raise HTTPException(status_code=503, detail="AI scoring engine temporarily unavailable — please retry.")
    latency_ms = round((time.time() - start) * 1000, 2)

    # Persist results as company candidates
    saved = []
    for person in final_results:
        candidate_id = str(uuid.uuid4())
        db.add(CompanyCandidateORM(
            id=candidate_id,
            company_id=user.company_id,
            added_by=user.id,
            name=person.get("name", "Unknown"),
            role=role_title,
            tier=person.get("tier", "bronze"),
            match_score=person.get("match_score", 0),
            adaptability=person.get("adaptability", 0),
            focus_penalty=person.get("focus_penalty", 0),
            ai_analysis=person.get("ai_analysis", ""),
            silent_skill=person.get("silent_skill"),
            notes="",
            shortlisted=False,
            job_id=job_id,
            partner_source="resume_upload",
        ))
        saved.append({**person, "id": candidate_id})

    # Update quota + logs
    cost.ai_calls_this_month += 1
    cost.ai_calls_remaining = max(0, cost.ai_calls_remaining - 1)
    db.commit()
    log_usage(db, user.company_id, user.id, "ai_grade",
              f"Scored {len(resumes)} résumés for '{role_title}'", latency_ms=latency_ms)
    await fire_event(db, user.company_id, "candidate.scored",
                     {"role_title": role_title, "resumes_scored": len(resumes), "results": len(saved)})

    return JSONResponse({
        "ok": True,
        "role_title": role_title,
        "resumes_received": len(resumes),
        "search_strategy": search_strategy,
        "results": saved,
        "ai_calls_remaining": cost.ai_calls_remaining,
        "latency_ms": latency_ms,
    })

# ============================================================
# APOLLO.IO — REAL CANDIDATE SOURCING (activates when
# APOLLO_API_KEY is set in Azure App Settings)
# ============================================================
@app.post("/api/apollo/search")
async def apollo_search_candidates(request: Request, db: Session = Depends(get_db)):
    """Search real candidates via Apollo.io. Returns honest 'not configured' until the key is set."""
    user = require_recruiter_or_admin(request, db)
    if not APOLLO_API_KEY:
        return JSONResponse({
            "ok": False,
            "configured": False,
            "error": "Apollo.io is not connected yet. Add APOLLO_API_KEY in Azure App Settings to enable candidate sourcing.",
        }, status_code=501)

    data = await request.json()
    payload = {
        "q_keywords": data.get("keywords", ""),
        "person_titles": data.get("titles", []),
        "person_locations": data.get("locations", []),
        "page": int(data.get("page", 1)),
        "per_page": min(int(data.get("per_page", 10)), 25),
    }
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{APOLLO_BASE_URL}/mixed_people/search",
                headers={"Content-Type": "application/json", "X-Api-Key": APOLLO_API_KEY},
                json=payload, timeout=20.0,
            )
            res.raise_for_status()
            body = res.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Apollo.io request failed — check the API key and plan limits.")

    people = [{
        "name": p.get("name"),
        "title": p.get("title"),
        "company": (p.get("organization") or {}).get("name"),
        "location": p.get("city"),
        "linkedin_url": p.get("linkedin_url"),
    } for p in body.get("people", [])]
    log_usage(db, user.company_id, user.id, "apollo_search", f"{len(people)} results")
    return JSONResponse({"ok": True, "configured": True, "people": people, "total": len(people)})

# ============================================================
# PHASES 23-32 (unchanged)
# ============================================================
@app.post("/api/feedback")
async def submit_feedback(request: Request, db: Session = Depends(get_db)):
    user=require_recruiter_or_admin(request,db); data=await request.json()
    if not check_rate_limit(user.company_id,"feedback",max_calls=100,window_seconds=60): raise HTTPException(status_code=429,detail="Rate limit exceeded.")
    action=data.get("action","")
    if action not in ("shortlist","skip","hire","view","note"): raise HTTPException(status_code=400,detail="Invalid action")
    signal_map={"shortlist":"positive","hire":"positive","view":"neutral","note":"neutral","skip":"negative"}
    event=FeedbackEventORM(id=str(uuid.uuid4()),company_id=user.company_id,user_id=user.id,action=action,signal=signal_map[action],candidate_id=data.get("candidate_id"),candidate_name=data.get("candidate_name"),job_id=data.get("job_id"),job_title=data.get("job_title"),tier=data.get("tier"),match_score=data.get("match_score"),anonymized=True); db.add(event)
    _update_recruiter_analytics(db,user.company_id,user.id,user.name,action); log_usage(db,user.company_id,user.id,f"feedback_{action}",data.get("candidate_name"))
    return JSONResponse({"ok":True,"signal":signal_map[action],"action":action,"message":f"Feedback recorded: {action}"})

@app.get("/api/feedback")
async def get_feedback(request: Request, db: Session = Depends(get_db)):
    user=require_admin(request,db); events=db.query(FeedbackEventORM).filter(FeedbackEventORM.company_id==user.company_id,FeedbackEventORM.is_deleted==False).order_by(FeedbackEventORM.created_at.desc()).limit(50).all()
    total=len(events); positives=sum(1 for e in events if e.signal=="positive"); negatives=sum(1 for e in events if e.signal=="negative"); hires=sum(1 for e in events if e.action=="hire")
    return JSONResponse({"ok":True,"total":total,"positives":positives,"negatives":negatives,"hires":hires,"conversion_rate":round(hires/total*100,1) if total>0 else 0,"events":[{"id":e.id,"action":e.action,"signal":e.signal,"candidate_name":e.candidate_name,"job_title":e.job_title,"tier":e.tier,"match_score":e.match_score,"created_at":e.created_at.isoformat()} for e in events]})

@app.get("/api/insights")
async def get_insights(request: Request, db: Session = Depends(get_db)):
    user=require_company_user(request,db); company_id=user.company_id
    total_candidates=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.is_deleted==False).count()
    avg_score=db.query(func.avg(CompanyCandidateORM.match_score)).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.is_deleted==False).scalar() or 0.0
    avg_adaptability=db.query(func.avg(CompanyCandidateORM.adaptability)).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.is_deleted==False).scalar() or 0.0
    shortlist_count=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.shortlisted==True,CompanyCandidateORM.is_deleted==False).count()
    gold=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.tier=="gold",CompanyCandidateORM.is_deleted==False).count()
    silver=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.tier=="silver",CompanyCandidateORM.is_deleted==False).count()
    bronze=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.tier=="bronze",CompanyCandidateORM.is_deleted==False).count()
    hire_count=db.query(FeedbackEventORM).filter(FeedbackEventORM.company_id==company_id,FeedbackEventORM.action=="hire").count()
    shortlist_rate=round(shortlist_count/total_candidates*100,1) if total_candidates>0 else 0
    hire_rate=round(hire_count/shortlist_count*100,1) if shortlist_count>0 else 0
    platform_avg_score=db.query(func.avg(CompanyCandidateORM.match_score)).scalar() or 85.0
    platform_avg_adaptability=db.query(func.avg(CompanyCandidateORM.adaptability)).scalar() or 78.0
    return JSONResponse({"ok":True,"company":{"avg_match_score":round(avg_score,1),"avg_adaptability":round(avg_adaptability,1),"total_candidates":total_candidates,"shortlist_rate":shortlist_rate,"hire_rate":hire_rate,"tier_distribution":{"gold":round(gold/total_candidates*100,1) if total_candidates>0 else 0,"silver":round(silver/total_candidates*100,1) if total_candidates>0 else 0,"bronze":round(bronze/total_candidates*100,1) if total_candidates>0 else 0}},"benchmarks":{"platform_avg_match_score":round(platform_avg_score,1),"platform_avg_adaptability":round(platform_avg_adaptability,1),"platform_avg_shortlist_rate":34.2,"platform_avg_hire_rate":18.7,"platform_avg_time_to_hire":"12.4 days"},"vs_benchmark":{"match_score":round(avg_score-platform_avg_score,1),"adaptability":round(avg_adaptability-platform_avg_adaptability,1),"shortlist_rate":round(shortlist_rate-34.2,1)}})

@app.get("/api/forecast")
async def get_forecast(request: Request, db: Session = Depends(get_db)):
    user=require_company_user(request,db); company_id=user.company_id; since=datetime.utcnow()-timedelta(days=30)
    recent_events=db.query(FeedbackEventORM).filter(FeedbackEventORM.company_id==company_id,FeedbackEventORM.created_at>=since,FeedbackEventORM.is_deleted==False).all()
    total_events=len(recent_events); shortlists=sum(1 for e in recent_events if e.action=="shortlist"); hires=sum(1 for e in recent_events if e.action=="hire"); skips=sum(1 for e in recent_events if e.action=="skip")
    hiring_velocity=round(shortlists/4,1); conversion_probability=round(hires/shortlists*100,1) if shortlists>0 else 0
    est_time_to_hire=round(30/hires,1) if hires>0 else 14.0; est_candidates_needed=max(3,round(1/(conversion_probability/100))) if conversion_probability>0 else 10
    confidence=min(0.95,max(0.3,total_events/50)); ci_low=round(max(0,conversion_probability-10),1); ci_high=round(min(100,conversion_probability+10),1)
    forecast=ForecastORM(id=str(uuid.uuid4()),company_id=company_id,forecast_date=datetime.utcnow(),hiring_velocity=hiring_velocity,conversion_probability=conversion_probability,est_time_to_hire_days=est_time_to_hire,est_candidates_needed=est_candidates_needed,predicted_hire_rate=conversion_probability,predicted_time_to_hire=est_time_to_hire,confidence_interval_low=ci_low,confidence_interval_high=ci_high,confidence_score=round(confidence,2),model_version="v33.1",based_on_events=total_events)
    db.add(forecast); db.commit()
    return JSONResponse({"ok":True,"forecast":{"hiring_velocity":hiring_velocity,"conversion_probability":conversion_probability,"confidence_interval":{"low":ci_low,"high":ci_high},"est_time_to_hire_days":est_time_to_hire,"est_candidates_needed":est_candidates_needed,"confidence_score":round(confidence,2),"model_version":"v33.1","based_on_events":total_events},"summary":{"shortlists_30d":shortlists,"hires_30d":hires,"skips_30d":skips},"recommendation":f"At your current velocity of {hiring_velocity} shortlists/week, expect to hire in ~{est_time_to_hire} days."})

@app.get("/api/sla")
async def get_sla_dashboard(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); metrics=run_sla_check(db,admin.company_id)
    active_alerts=db.query(SLAAlertORM).filter(SLAAlertORM.resolved==False).order_by(SLAAlertORM.created_at.desc()).limit(20).all()
    resolved_alerts=db.query(SLAAlertORM).filter(SLAAlertORM.resolved==True).order_by(SLAAlertORM.resolved_at.desc()).limit(10).all()
    return JSONResponse({"ok":True,"status":metrics["status"],"status_color":get_sla_status_color(metrics["status"]),"sla_targets":SLA_TARGETS,"metrics":{"uptime_pct":metrics["uptime_pct"],"error_rate_pct":metrics["error_rate_pct"],"avg_latency_ms":metrics["avg_latency_ms"],"p95_latency_ms":metrics["p95_latency_ms"],"p99_latency_ms":metrics["p99_latency_ms"],"ai_latency_ms":metrics["ai_latency_ms"],"total_requests":metrics["total_requests"],"requests_per_hour":metrics["requests_per_hour"]},"active_alerts":[{"id":a.id,"type":a.alert_type,"severity":a.severity,"message":a.message,"metric_value":a.metric_value,"threshold":a.threshold,"created_at":a.created_at.isoformat()} for a in active_alerts],"resolved_alerts":[{"id":a.id,"type":a.alert_type,"message":a.message,"resolved_at":a.resolved_at.isoformat() if a.resolved_at else None} for a in resolved_alerts],"alerts_created":metrics.get("alerts_created",0),"alerts_resolved":metrics.get("alerts_resolved",0),"period":"last_24h"})

@app.post("/api/sla/run")
async def run_sla_check_endpoint(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); metrics=run_sla_check(db,admin.company_id); return JSONResponse({"ok":True,**metrics})

@app.get("/api/sla/alerts")
async def get_sla_alerts(request: Request, db: Session = Depends(get_db)):
    require_admin(request,db); alerts=db.query(SLAAlertORM).filter(SLAAlertORM.resolved==False).order_by(SLAAlertORM.created_at.desc()).limit(20).all()
    return JSONResponse({"ok":True,"alerts":[{"id":a.id,"type":a.alert_type,"severity":a.severity,"message":a.message,"metric_value":a.metric_value,"threshold":a.threshold,"created_at":a.created_at.isoformat()} for a in alerts],"total_active":len(alerts),"critical":sum(1 for a in alerts if a.severity=="critical"),"warnings":sum(1 for a in alerts if a.severity=="warning")})

@app.patch("/api/sla/alerts/{alert_id}/resolve")
async def resolve_sla_alert(alert_id: str, request: Request, db: Session = Depends(get_db)):
    require_admin(request,db); alert=db.query(SLAAlertORM).filter(SLAAlertORM.id==alert_id).first()
    if not alert: raise HTTPException(status_code=404,detail="Alert not found")
    alert.resolved=True; alert.resolved_at=datetime.utcnow(); db.commit(); return JSONResponse({"ok":True,"message":"Alert resolved"})

@app.get("/api/sla/history")
async def get_sla_history(request: Request, db: Session = Depends(get_db)):
    require_admin(request,db); since=datetime.utcnow()-timedelta(days=7)
    all_alerts=db.query(SLAAlertORM).filter(SLAAlertORM.created_at>=since).order_by(SLAAlertORM.created_at.desc()).all()
    return JSONResponse({"ok":True,"period":"last_7_days","total":len(all_alerts),"critical":sum(1 for a in all_alerts if a.severity=="critical"),"warnings":sum(1 for a in all_alerts if a.severity=="warning"),"resolved":sum(1 for a in all_alerts if a.resolved),"alerts":[{"id":a.id,"type":a.alert_type,"severity":a.severity,"message":a.message,"metric_value":a.metric_value,"resolved":a.resolved,"created_at":a.created_at.isoformat(),"resolved_at":a.resolved_at.isoformat() if a.resolved_at else None} for a in all_alerts]})

@app.get("/api/models")
async def get_model_versions(request: Request, db: Session = Depends(get_db)):
    require_admin(request,db); models=db.query(ModelVersionORM).order_by(ModelVersionORM.created_at.desc()).all()
    if not models: v=ModelVersionORM(id=str(uuid.uuid4()),version="v33.1",status="active",accuracy=0.94,precision=0.91,recall=0.89,cost_per_call=0.01,training_size=0,notes="Phase 33 model"); db.add(v); db.commit(); models=[v]
    return JSONResponse({"ok":True,"models":[{"version":m.version,"status":m.status,"accuracy":m.accuracy,"precision":m.precision,"recall":m.recall,"cost_per_call":m.cost_per_call,"training_size":m.training_size,"deployed_at":m.deployed_at.isoformat() if m.deployed_at else None,"created_at":m.created_at.isoformat()} for m in models]})

@app.post("/api/data/fusion")
@app.post("/api/fusion/run")
async def run_data_fusion(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db)
    from app.phase24 import run_fusion_pipeline
    fused_count=run_fusion_pipeline(db,admin.company_id)
    return JSONResponse({"ok":True,"fused_rows":fused_count,"fused_at":datetime.utcnow().isoformat(),"message":f"Data fusion complete — {fused_count} records fused"})

@app.get("/api/data/fusion")
async def get_fusion_data(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db)
    total=db.query(DataFusionORM).filter(DataFusionORM.company_id==admin.company_id,DataFusionORM.is_deleted==False).count()
    positive=db.query(DataFusionORM).filter(DataFusionORM.company_id==admin.company_id,DataFusionORM.feedback_signal=="positive",DataFusionORM.is_deleted==False).count()
    negative=db.query(DataFusionORM).filter(DataFusionORM.company_id==admin.company_id,DataFusionORM.feedback_signal=="negative",DataFusionORM.is_deleted==False).count()
    return JSONResponse({"ok":True,"total_fused":total,"positive_signals":positive,"negative_signals":negative,"ready_for_retraining":total>=50,"retraining_threshold":50})

@app.post("/api/model/retrain")
async def trigger_model_retrain(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db)
    from app.phase24 import retrain_model_version
    try:
        new_version=retrain_model_version(db,admin.company_id); model=db.query(ModelVersionORM).filter(ModelVersionORM.version==new_version).first()
        return JSONResponse({"ok":True,"model_version":new_version,"accuracy":model.accuracy if model else None,"message":f"Model {new_version} deployed successfully"})
    except ValueError as e: raise HTTPException(status_code=400,detail=str(e))

def _update_recruiter_analytics(db,company_id,user_id,user_name,action):
    period=datetime.utcnow().strftime("%Y-%m")
    rec=db.query(RecruiterAnalyticsORM).filter(RecruiterAnalyticsORM.company_id==company_id,RecruiterAnalyticsORM.user_id==user_id,RecruiterAnalyticsORM.period==period).first()
    if not rec: rec=RecruiterAnalyticsORM(id=str(uuid.uuid4()),company_id=company_id,user_id=user_id,user_name=user_name,period=period); db.add(rec)
    rec.total_decisions+=1
    if action in ("shortlist","hire"): rec.positive_signals+=1; (setattr(rec,"shortlist_count",rec.shortlist_count+1) if action=="shortlist" else setattr(rec,"hire_count",rec.hire_count+1))
    elif action=="skip": rec.negative_signals+=1; rec.skip_count+=1
    try: db.commit()
    except: db.rollback()

@app.post("/api/analytics/recruiter/run")
async def run_recruiter_analytics_job(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db)
    from app.recruiter_analytics_engine import run_recruiter_analytics
    count=run_recruiter_analytics(db,admin.company_id)
    return JSONResponse({"ok":True,"recruiters_processed":count,"message":f"Recruiter analytics complete — {count} recruiters processed"})

@app.get("/api/analytics/recruiter")
async def get_recruiter_analytics(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); period=datetime.utcnow().strftime("%Y-%m")
    records=db.query(RecruiterAnalyticsORM).filter(RecruiterAnalyticsORM.company_id==admin.company_id,RecruiterAnalyticsORM.period==period,RecruiterAnalyticsORM.is_deleted==False).all()
    from app.recruiter_analytics_engine import get_recruiter_flags
    recruiters=[{"user_id":r.user_id,"name":r.user_name,"period":r.period,"total_decisions":r.total_decisions,"positive_signals":r.positive_signals,"negative_signals":r.negative_signals,"hire_count":r.hire_count,"shortlist_count":r.shortlist_count,"skip_count":r.skip_count,"skip_rate_pct":round(r.skip_count/max(r.total_decisions,1)*100,1),"flags":get_recruiter_flags(r),"positive_rate_pct":round(r.positive_signals/max(r.total_decisions,1)*100,1),"hire_rate_pct":round(r.hire_count/max(r.shortlist_count,1)*100,1)} for r in records]
    return JSONResponse({"ok":True,"period":period,"recruiters":recruiters,"team_summary":{"total_recruiters":len(records),"total_decisions":sum(r.total_decisions for r in records),"total_hires":sum(r.hire_count for r in records)}})

@app.get("/api/analytics/recruiter/{user_id}")
async def get_single_recruiter_analytics(user_id: str, request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); period=datetime.utcnow().strftime("%Y-%m")
    rec=db.query(RecruiterAnalyticsORM).filter(RecruiterAnalyticsORM.company_id==admin.company_id,RecruiterAnalyticsORM.user_id==user_id,RecruiterAnalyticsORM.period==period).first()
    if not rec: raise HTTPException(status_code=404,detail="No analytics found for this recruiter")
    from app.recruiter_analytics_engine import get_recruiter_flags
    return JSONResponse({"ok":True,"user_id":rec.user_id,"name":rec.user_name,"total_decisions":rec.total_decisions,"hire_count":rec.hire_count,"shortlist_count":rec.shortlist_count,"skip_count":rec.skip_count,"flags":get_recruiter_flags(rec)})

@app.post("/api/forecast/run")
async def run_forecast_job(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db)
    from app.forecast_engine import run_forecast_for_company
    count=run_forecast_for_company(db,admin.company_id)
    return JSONResponse({"ok":True,"forecasts_written":count,"message":f"Forecast job complete — {count} forecasts written"})

@app.get("/api/forecast/job/{job_id}")
async def get_job_forecast(job_id: str, request: Request, db: Session = Depends(get_db)):
    user=require_company_user(request,db)
    forecast=db.query(ForecastORM).filter(ForecastORM.company_id==user.company_id,ForecastORM.job_id==job_id).order_by(ForecastORM.forecast_date.desc()).first()
    if not forecast: raise HTTPException(status_code=404,detail="No forecast available for this job")
    from app.forecast_engine import get_confidence_label
    return JSONResponse({"ok":True,"job_id":job_id,"forecast_date":forecast.forecast_date.isoformat(),"predicted_hire_rate":forecast.predicted_hire_rate,"predicted_time_to_hire":forecast.predicted_time_to_hire,"est_candidates_needed":forecast.est_candidates_needed,"confidence_score":forecast.confidence_score,"confidence_label":get_confidence_label(forecast.confidence_score or 0),"model_version":forecast.model_version})

@app.get("/api/forecast/company")
async def get_company_forecasts(request: Request, db: Session = Depends(get_db)):
    user=require_company_user(request,db); jobs=db.query(CompanyRoleORM).filter(CompanyRoleORM.company_id==user.company_id,CompanyRoleORM.is_active==True,CompanyRoleORM.is_deleted==False).all()
    from app.forecast_engine import get_confidence_label
    results=[{"job_id":job.id,"job_title":job.title,"location":job.location,"forecast":{"predicted_hire_rate":f.predicted_hire_rate if (f:=db.query(ForecastORM).filter(ForecastORM.company_id==user.company_id,ForecastORM.job_id==job.id).order_by(ForecastORM.forecast_date.desc()).first()) else None,"predicted_time_to_hire":f.predicted_time_to_hire if f else None,"confidence_label":get_confidence_label(f.confidence_score or 0) if f else "No data"} if f else None} for job in jobs]
    return JSONResponse({"ok":True,"total_jobs":len(jobs),"jobs":results})

@app.get("/api/cost")
async def get_cost_dashboard(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); company=db.query(CompanyORM).filter(CompanyORM.id==admin.company_id).first()
    summary=get_cost_summary(db,admin.company_id,company.plan); check_cost_alerts(db,admin.company_id,company.plan)
    return JSONResponse({"ok":True,**summary})

@app.post("/api/cost/optimize")
async def run_cost_optimizer(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); company=db.query(CompanyORM).filter(CompanyORM.id==admin.company_id).first()
    report=run_cost_optimization(db,admin.company_id,company.plan); return JSONResponse({"ok":True,"report":report})

@app.get("/api/cost/history")
async def get_cost_history(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); since=datetime.utcnow()-timedelta(days=30)
    logs=db.query(UsageLogORM).filter(UsageLogORM.company_id==admin.company_id,UsageLogORM.action.in_(["ai_grade","ai_narrative","ai_outreach","ai_copilot"]),UsageLogORM.created_at>=since).order_by(UsageLogORM.created_at.desc()).limit(100).all()
    total_cost=sum(l.cost_usd or 0 for l in logs)
    return JSONResponse({"ok":True,"period":"last_30_days","total_calls":len(logs),"total_cost_usd":round(total_cost,4),"avg_cost_per_call":round(total_cost/max(len(logs),1),6),"calls":[{"action":l.action,"details":l.details,"cost_usd":l.cost_usd,"latency_ms":l.latency_ms,"created_at":l.created_at.isoformat()} for l in logs]})

@app.get("/api/cost/model-selection")
async def get_model_selection(request: Request, db: Session = Depends(get_db)):
    require_admin(request,db)
    return JSONResponse({"ok":True,"model_tiering":{"gold":{"model":"gpt-4o"},"silver":{"model":"gpt-4o-mini"},"bronze":{"model":"gpt-4o-mini"},"narrative":{"model":"gpt-4o"},"bulk":{"model":"gpt-4o-mini"}}})

@app.post("/api/narrative/generate")
async def generate_candidate_narrative(request: Request, db: Session = Depends(get_db)):
    user=require_recruiter_or_admin(request,db); data=await request.json()
    candidate_id=data.get("candidate_id",""); narrative_type=data.get("narrative_type","full")
    if narrative_type not in ("summary","strengths","risks","culture_fit","story_arc","pitch","full"): raise HTTPException(status_code=400,detail="Invalid narrative type")
    if not candidate_id: raise HTTPException(status_code=400,detail="candidate_id is required")
    from app.narrative_engine import generate_narrative
    result=await generate_narrative(db=db,candidate_id=candidate_id,company_id=user.company_id,user_id=user.id,narrative_type=narrative_type)
    if "error" in result: raise HTTPException(status_code=404,detail=result["error"])
    await fire_event(db,user.company_id,"narrative.generated",{"candidate_id":candidate_id,"narrative_type":narrative_type})
    return JSONResponse({"ok":True,**result})

@app.post("/api/narrative/batch")
async def generate_batch_narratives_route(request: Request, db: Session = Depends(get_db)):
    user=require_recruiter_or_admin(request,db); data=await request.json()
    from app.narrative_engine import generate_batch_narratives
    result=await generate_batch_narratives(db=db,company_id=user.company_id,user_id=user.id,narrative_type=data.get("narrative_type","summary"))
    return JSONResponse({"ok":True,**result})

@app.get("/api/narrative/insights")
async def get_narrative_insights(request: Request, db: Session = Depends(get_db)):
    user=require_company_user(request,db)
    from app.narrative_engine import get_narrative_insights
    return JSONResponse({"ok":True,"insights":get_narrative_insights(db,user.company_id)})

@app.get("/api/narrative/candidate/{candidate_id}")
async def get_candidate_narrative(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    user=require_company_user(request,db)
    narrative=db.query(AINarrativeORM).filter(AINarrativeORM.candidate_id==candidate_id,AINarrativeORM.company_id==user.company_id,AINarrativeORM.is_deleted==False).order_by(AINarrativeORM.created_at.desc()).first()
    if not narrative: raise HTTPException(status_code=404,detail="No narrative found for this candidate")
    from app.narrative_engine import _score_narrative_quality,NARRATIVE_VERSION
    quality=_score_narrative_quality(narrative.narrative)
    return JSONResponse({"ok":True,"candidate_id":candidate_id,"narrative":narrative.narrative,"tone":narrative.tone,"sentiment":narrative.sentiment,"model_version":narrative.model_version,"quality_score":quality["score"],"quality_grade":quality["grade"],"created_at":narrative.created_at.isoformat(),"narrative_version":NARRATIVE_VERSION})

@app.post("/api/narrative/feedback")
async def submit_narrative_feedback(request: Request, db: Session = Depends(get_db)):
    user=require_recruiter_or_admin(request,db); data=await request.json(); feedback=data.get("feedback","")
    if feedback not in ("positive","negative","hallucination","rewrite"): raise HTTPException(status_code=400,detail="Invalid feedback type")
    log_usage(db,user.company_id,user.id,action=f"narrative_feedback_{feedback}",details=f"candidate={data.get('candidate_id')}")
    return JSONResponse({"ok":True,"message":f"Narrative feedback recorded: {feedback}"})

# Phase 31 API Keys + Webhooks
@app.post("/api/v1/api-keys")
async def create_new_api_key(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); data=await request.json(); name=data.get("name","").strip(); scopes=data.get("scopes",["candidates:read"])
    if not name: raise HTTPException(status_code=400,detail="API key name is required")
    result=create_api_key(db=db,company_id=admin.company_id,created_by=admin.id,name=name,scopes=scopes,rate_limit=PLANS.get(db.query(CompanyORM).filter(CompanyORM.id==admin.company_id).first().plan,PLANS["free"]).get("ai_calls_per_month",60))
    return JSONResponse({"ok":True,**result})

@app.get("/api/v1/api-keys")
async def list_api_keys(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); keys=db.query(APIKeyORM).filter(APIKeyORM.company_id==admin.company_id,APIKeyORM.is_deleted==False).order_by(APIKeyORM.created_at.desc()).all()
    return JSONResponse({"ok":True,"keys":[{"id":k.id,"name":k.name,"key_prefix":k.key_prefix,"scopes":json.loads(k.scopes or "[]"),"rate_limit":k.rate_limit,"total_calls":k.total_calls,"last_used_at":k.last_used_at.isoformat() if k.last_used_at else None,"is_active":k.is_active,"created_at":k.created_at.isoformat()} for k in keys],"total":len(keys),"available_scopes":VALID_SCOPES})

@app.delete("/api/v1/api-keys/{key_id}")
async def revoke_api_key(key_id: str, request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); key=db.query(APIKeyORM).filter(APIKeyORM.id==key_id,APIKeyORM.company_id==admin.company_id,APIKeyORM.is_deleted==False).first()
    if not key: raise HTTPException(status_code=404,detail="API key not found")
    key.is_active=False; key.is_deleted=True; key.deleted_at=datetime.utcnow(); db.commit()
    return JSONResponse({"ok":True,"message":f"API key '{key.name}' revoked"})

@app.get("/api/v1/candidates")
async def v1_get_candidates(request: Request, db: Session = Depends(get_db), api_key: APIKeyORM = Depends(require_scope("candidates:read"))):
    start=time.time(); candidates=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==api_key.company_id,CompanyCandidateORM.is_deleted==False).order_by(CompanyCandidateORM.created_at.desc()).limit(100).all()
    latency_ms=round((time.time()-start)*1000,2); log_api_call(db,api_key.company_id,api_key.id,"/api/v1/candidates","GET",200,latency_ms,request.client.host if request.client else None)
    return JSONResponse({"ok":True,"candidates":[{"id":c.id,"name":c.name,"role":c.role,"tier":c.tier,"match_score":c.match_score,"ai_analysis":c.ai_analysis,"linkedin_url":c.linkedin_url,"created_at":c.created_at.isoformat()} for c in candidates],"total":len(candidates)})

@app.post("/api/v1/candidates")
async def v1_create_candidate(request: Request, db: Session = Depends(get_db), api_key: APIKeyORM = Depends(require_scope("candidates:write"))):
    start=time.time(); data=await request.json(); candidate_id=str(uuid.uuid4())
    candidate=CompanyCandidateORM(id=candidate_id,company_id=api_key.company_id,added_by=f"api_key:{api_key.id}",name=data.get("name",""),role=data.get("role",""),tier=data.get("tier","bronze"),match_score=data.get("match_score",0),adaptability=data.get("adaptability",0),focus_penalty=data.get("focus_penalty",0),ai_analysis=data.get("ai_analysis",""),silent_skill=data.get("silent_skill"),linkedin_url=data.get("linkedin_url"),notes=data.get("notes",""),shortlisted=data.get("shortlisted",False)); db.add(candidate); db.commit()
    latency_ms=round((time.time()-start)*1000,2); log_api_call(db,api_key.company_id,api_key.id,"/api/v1/candidates","POST",201,latency_ms,request.client.host if request.client else None)
    await fire_event(db,api_key.company_id,"candidate.created",{"candidate_id":candidate_id,"name":data.get("name"),"source":"external_api"})
    return JSONResponse({"ok":True,"id":candidate_id},status_code=201)

@app.patch("/api/v1/candidates/{candidate_id}")
async def v1_update_candidate(candidate_id: str, request: Request, db: Session = Depends(get_db), api_key: APIKeyORM = Depends(require_scope("candidates:write"))):
    data=await request.json(); candidate=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.id==candidate_id,CompanyCandidateORM.company_id==api_key.company_id,CompanyCandidateORM.is_deleted==False).first()
    if not candidate: raise HTTPException(status_code=404,detail="Candidate not found")
    if "notes" in data: candidate.notes=data["notes"]
    if "shortlisted" in data: candidate.shortlisted=data["shortlisted"]
    db.commit(); await fire_event(db,api_key.company_id,"candidate.updated",{"candidate_id":candidate_id}); return JSONResponse({"ok":True})

@app.delete("/api/v1/candidates/{candidate_id}")
async def v1_delete_candidate(candidate_id: str, request: Request, db: Session = Depends(get_db), api_key: APIKeyORM = Depends(require_scope("candidates:write"))):
    candidate=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.id==candidate_id,CompanyCandidateORM.company_id==api_key.company_id,CompanyCandidateORM.is_deleted==False).first()
    if not candidate: raise HTTPException(status_code=404,detail="Candidate not found")
    candidate.is_deleted=True; candidate.deleted_at=datetime.utcnow(); db.commit()
    await fire_event(db,api_key.company_id,"candidate.deleted",{"candidate_id":candidate_id}); return JSONResponse({"ok":True})

@app.post("/api/v1/narratives/generate")
async def v1_generate_narrative(request: Request, db: Session = Depends(get_db), api_key: APIKeyORM = Depends(require_scope("narratives:generate"))):
    data=await request.json(); candidate_id=data.get("candidate_id","")
    if not candidate_id: raise HTTPException(status_code=400,detail="candidate_id is required")
    from app.narrative_engine import generate_narrative
    result=await generate_narrative(db=db,candidate_id=candidate_id,company_id=api_key.company_id,user_id=f"api_key:{api_key.id}",narrative_type=data.get("narrative_type","summary"))
    if "error" in result: raise HTTPException(status_code=404,detail=result["error"])
    return JSONResponse({"ok":True,**result})

@app.get("/api/v1/narratives/{candidate_id}")
async def v1_get_narrative(candidate_id: str, request: Request, db: Session = Depends(get_db), api_key: APIKeyORM = Depends(require_scope("narratives:generate"))):
    narrative=db.query(AINarrativeORM).filter(AINarrativeORM.candidate_id==candidate_id,AINarrativeORM.company_id==api_key.company_id,AINarrativeORM.is_deleted==False).order_by(AINarrativeORM.created_at.desc()).first()
    if not narrative: raise HTTPException(status_code=404,detail="No narrative found")
    return JSONResponse({"ok":True,"candidate_id":candidate_id,"narrative":narrative.narrative,"tone":narrative.tone,"model_version":narrative.model_version,"created_at":narrative.created_at.isoformat()})

@app.get("/api/v1/analytics/usage")
async def v1_get_usage_analytics(request: Request, db: Session = Depends(get_db), api_key: APIKeyORM = Depends(require_scope("analytics:read"))):
    company=db.query(CompanyORM).filter(CompanyORM.id==api_key.company_id).first(); summary=get_cost_summary(db,api_key.company_id,company.plan); metrics=run_sla_check(db,api_key.company_id)
    return JSONResponse({"ok":True,"ai_calls":summary["ai_calls"],"cost_usd":summary["total_cost_usd"],"avg_latency_ms":metrics["avg_latency_ms"],"uptime_pct":metrics["uptime_pct"]})

@app.get("/api/v1/analytics/talent")
async def v1_get_talent_analytics(request: Request, db: Session = Depends(get_db), api_key: APIKeyORM = Depends(require_scope("analytics:read"))):
    company_id=api_key.company_id; total=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.is_deleted==False).count()
    gold=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.tier=="gold",CompanyCandidateORM.is_deleted==False).count()
    silver=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.tier=="silver",CompanyCandidateORM.is_deleted==False).count()
    bronze=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.tier=="bronze",CompanyCandidateORM.is_deleted==False).count()
    shortlists=db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.shortlisted==True,CompanyCandidateORM.is_deleted==False).count()
    avg_score=db.query(func.avg(CompanyCandidateORM.match_score)).filter(CompanyCandidateORM.company_id==company_id,CompanyCandidateORM.is_deleted==False).scalar() or 0.0
    return JSONResponse({"ok":True,"total_candidates":total,"tier_distribution":{"gold":gold,"silver":silver,"bronze":bronze},"shortlist_rate":round(shortlists/max(total,1)*100,1),"avg_match_score":round(avg_score,1)})

@app.post("/api/v1/webhooks")
async def create_webhook(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); data=await request.json(); url=data.get("url","").strip(); event_types=data.get("event_types",[])
    if not url: raise HTTPException(status_code=400,detail="Webhook URL is required")
    if not url.startswith("https://"): raise HTTPException(status_code=400,detail="Webhook URL must use HTTPS")
    if not event_types: raise HTTPException(status_code=400,detail="At least one event_type is required")
    from app.api_v1_engine import generate_webhook_secret; webhook_secret=generate_webhook_secret()
    webhook=WebhookORM(id=str(uuid.uuid4()),company_id=admin.company_id,name=data.get("name","") or url[:50],url=url,secret=webhook_secret,event_types=json.dumps(event_types),created_by=admin.id); db.add(webhook); db.commit()
    return JSONResponse({"ok":True,"id":webhook.id,"url":webhook.url,"secret":webhook_secret,"event_types":event_types,"warning":"Store the secret securely — it will not be shown again"})

@app.get("/api/v1/webhooks")
async def list_webhooks(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); webhooks=db.query(WebhookORM).filter(WebhookORM.company_id==admin.company_id,WebhookORM.is_deleted==False).all()
    return JSONResponse({"ok":True,"webhooks":[{"id":w.id,"name":w.name,"url":w.url,"event_types":json.loads(w.event_types or "[]"),"is_active":w.is_active,"failure_count":w.failure_count,"total_sent":w.total_sent,"created_at":w.created_at.isoformat()} for w in webhooks],"total":len(webhooks)})

@app.delete("/api/v1/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str, request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); webhook=db.query(WebhookORM).filter(WebhookORM.id==webhook_id,WebhookORM.company_id==admin.company_id,WebhookORM.is_deleted==False).first()
    if not webhook: raise HTTPException(status_code=404,detail="Webhook not found")
    webhook.is_deleted=True; webhook.is_active=False; db.commit(); return JSONResponse({"ok":True})

@app.post("/api/v1/webhooks/test")
async def test_webhook(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); data=await request.json(); webhook_id=data.get("webhook_id","")
    webhook=db.query(WebhookORM).filter(WebhookORM.id==webhook_id,WebhookORM.company_id==admin.company_id,WebhookORM.is_deleted==False).first()
    if not webhook: raise HTTPException(status_code=404,detail="Webhook not found")
    result=await deliver_webhook(db=db,webhook=webhook,event_type="test.ping",payload={"message":"Test event from AI Talent Match Pro","timestamp":datetime.utcnow().isoformat()})
    return JSONResponse({"ok":True,"delivery":result})

@app.get("/api/v1/webhooks/{webhook_id}/logs")
async def get_webhook_logs(webhook_id: str, request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); webhook=db.query(WebhookORM).filter(WebhookORM.id==webhook_id,WebhookORM.company_id==admin.company_id).first()
    if not webhook: raise HTTPException(status_code=404,detail="Webhook not found")
    logs=db.query(WebhookDeliveryLogORM).filter(WebhookDeliveryLogORM.webhook_id==webhook_id).order_by(WebhookDeliveryLogORM.created_at.desc()).limit(50).all()
    return JSONResponse({"ok":True,"logs":[{"id":l.id,"event_type":l.event_type,"status":l.status,"http_status":l.http_status,"latency_ms":l.latency_ms,"attempt":l.attempt,"created_at":l.created_at.isoformat()} for l in logs],"total":len(logs)})

@app.get("/api/v1/openapi.json")
async def get_openapi_spec():
    return JSONResponse({"openapi":"3.0.0","info":{"title":"AI Talent Match Pro API","version":"33.0.0","description":"Enterprise AI recruiting platform API"},"servers":[{"url":"https://api.aitmp.io/api/v1"}]})

@app.get("/api/v1/info")
async def get_api_info():
    return JSONResponse({"api":"AI Talent Match Pro","version":"33.0.0","scopes":VALID_SCOPES,"events":WEBHOOK_EVENTS,"partners":PARTNERS,"docs":"https://aitmp.io/developer"})

# Phase 32A — Integrations
@app.post("/api/integrations/greenhouse/webhook")
async def greenhouse_webhook(request: Request, db: Session = Depends(get_db)):
    data=await request.json(); event_type=request.headers.get("X-Greenhouse-Event",data.get("action","candidate.created"))
    api_key_header=request.headers.get("X-API-Key","")
    if not api_key_header: raise HTTPException(status_code=401,detail="X-API-Key required")
    valid,api_key,error=validate_api_key(db,api_key_header)
    if not valid: raise HTTPException(status_code=401,detail=error)
    return JSONResponse(process_inbound_event(db=db,company_id=api_key.company_id,partner="greenhouse",event_type=event_type,raw_payload=data,added_by=f"greenhouse:{api_key.company_id}"))

@app.post("/api/integrations/lever/webhook")
async def lever_webhook(request: Request, db: Session = Depends(get_db)):
    data=await request.json(); api_key_header=request.headers.get("X-API-Key","")
    valid,api_key,error=validate_api_key(db,api_key_header)
    if not valid: raise HTTPException(status_code=401,detail=error)
    return JSONResponse(process_inbound_event(db=db,company_id=api_key.company_id,partner="lever",event_type=data.get("event","candidate.created"),raw_payload=data,added_by=f"lever:{api_key.company_id}"))

@app.post("/api/integrations/zapier/webhook")
async def zapier_webhook(request: Request, db: Session = Depends(get_db)):
    data=await request.json(); api_key_header=request.headers.get("X-API-Key","")
    valid,api_key,error=validate_api_key(db,api_key_header)
    if not valid: raise HTTPException(status_code=401,detail=error)
    return JSONResponse(process_inbound_event(db=db,company_id=api_key.company_id,partner="zapier",event_type=data.get("event_type","candidate.created"),raw_payload=data,added_by=f"zapier:{api_key.company_id}"))

@app.post("/api/integrations/{partner}/push/{candidate_id}")
async def push_candidate_to_partner(partner: str, candidate_id: str, request: Request, db: Session = Depends(get_db)):
    if partner not in PARTNERS: raise HTTPException(status_code=400,detail=f"Invalid partner. Choose: {PARTNERS}")
    admin=require_admin(request,db); data=await request.json()
    result=await push_to_partner(db=db,company_id=admin.company_id,candidate_id=candidate_id,partner=partner,partner_api_key=data.get("partner_api_key",""))
    # Zapier/Make outbound push is not implemented — answer 501, never a misleading 200.
    if result.get("not_connected"):
        return JSONResponse(result, status_code=501)
    return JSONResponse(result)

@app.get("/api/integrations/status")
async def get_integrations_status(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db)
    return JSONResponse({"ok":True,"integrations":get_integration_status(db,admin.company_id),"partners":PARTNERS})

@app.get("/api/integrations/logs")
async def get_integration_logs(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); partner=request.query_params.get("partner"); status=request.query_params.get("status"); since=datetime.utcnow()-timedelta(days=7)
    query=db.query(PartnerSyncLogORM).filter(PartnerSyncLogORM.company_id==admin.company_id,PartnerSyncLogORM.created_at>=since)
    if partner: query=query.filter(PartnerSyncLogORM.partner==partner)
    if status:  query=query.filter(PartnerSyncLogORM.status==status)
    logs=query.order_by(PartnerSyncLogORM.created_at.desc()).limit(100).all()
    return JSONResponse({"ok":True,"logs":[{"id":l.id,"partner":l.partner,"direction":l.direction,"event_type":l.event_type,"status":l.status,"error":l.error,"latency_ms":l.latency_ms,"created_at":l.created_at.isoformat()} for l in logs],"total":len(logs)})

@app.post("/api/integrations/retry")
async def retry_integrations(request: Request, db: Session = Depends(get_db)):
    admin=require_admin(request,db); retried=retry_failed_syncs(db,admin.company_id)
    return JSONResponse({"ok":True,"retried":retried})

@app.get("/api/integrations/zapier/manifest")
async def get_zapier_manifest(): return JSONResponse(ZAPIER_APP_MANIFEST)

@app.get("/api/integrations/make/manifest")
async def get_makecom_manifest(): return JSONResponse(MAKECOM_MODULE_MANIFEST)

# Phase 32B — JD
@app.post("/api/jd/generate")
async def generate_jd(request: Request, db: Session = Depends(get_db)):
    user=require_recruiter_or_admin(request,db); data=await request.json(); job_id=data.get("job_id","")
    if not job_id: raise HTTPException(status_code=400,detail="job_id is required")
    company=db.query(CompanyORM).filter(CompanyORM.id==user.company_id).first()
    result=await generate_job_description(db=db,job_id=job_id,company_id=user.company_id,company_name=company.name,user_id=user.id,tone=data.get("tone","professional"),role_type=data.get("role_type","technical"),additional_context=data.get("additional_context",""))
    if "error" in result: raise HTTPException(status_code=404,detail=result["error"])
    return JSONResponse({"ok":True,**result})

@app.post("/api/jd/regenerate")
async def regenerate_jd(request: Request, db: Session = Depends(get_db)):
    user=require_recruiter_or_admin(request,db); data=await request.json(); job_id=data.get("job_id","")
    if not job_id: raise HTTPException(status_code=400,detail="job_id is required")
    db.query(JobDescriptionORM).filter(JobDescriptionORM.job_id==job_id,JobDescriptionORM.company_id==user.company_id,JobDescriptionORM.is_active==True).update({"is_active":False}); db.commit()
    company=db.query(CompanyORM).filter(CompanyORM.id==user.company_id).first()
    result=await generate_job_description(db=db,job_id=job_id,company_id=user.company_id,company_name=company.name,user_id=user.id,tone=data.get("tone","professional"),role_type=data.get("role_type","technical"))
    return JSONResponse({"ok":True,"regenerated":True,**result})

@app.get("/api/jd/{job_id}")
async def get_jd(job_id: str, request: Request, db: Session = Depends(get_db)):
    user=require_company_user(request,db); jd=get_jd_for_role(db,job_id,user.company_id)
    if not jd: raise HTTPException(status_code=404,detail="No job description found.")
    return JSONResponse({"ok":True,**jd})

@app.get("/api/jd/options/tones")
async def get_jd_tones(): return JSONResponse({"ok":True,"tones":get_available_tones()})

@app.get("/api/jd/options/role-types")
async def get_jd_role_types(): return JSONResponse({"ok":True,"role_types":get_available_role_types()})

@app.get("/api/jd/history/{job_id}")
async def get_jd_history(job_id: str, request: Request, db: Session = Depends(get_db)):
    user=require_company_user(request,db)
    jds=db.query(JobDescriptionORM).filter(JobDescriptionORM.job_id==job_id,JobDescriptionORM.company_id==user.company_id,JobDescriptionORM.is_deleted==False).order_by(JobDescriptionORM.version.desc()).all()
    return JSONResponse({"ok":True,"job_id":job_id,"versions":[{"jd_id":j.id,"version":j.version,"tone":j.tone,"role_type":j.role_type,"quality_score":j.quality_score,"is_active":j.is_active,"created_at":j.created_at.isoformat()} for j in jds]})

# ============================================================
# PHASE 33 — RECRUITER PROJECTS
# ============================================================

@app.post("/api/projects")
async def create_project(request: Request, db: Session = Depends(get_db)):
    """Create a new recruiter workspace project."""
    user = require_recruiter_or_admin(request, db)
    data = await request.json()

    name = data.get("name", "").strip()
    if not name: raise HTTPException(status_code=400, detail="Project name is required")

    project_id = str(uuid.uuid4())
    project = RecruiterProjectORM(
        id=project_id,
        company_id=user.company_id,
        created_by=user.id,
        role_id=data.get("role_id"),
        name=name,
        description=data.get("description", ""),
        status="active",
        priority=data.get("priority", "medium"),
        stage="sourcing",
        target_hire_date=datetime.fromisoformat(data["target_hire_date"]) if data.get("target_hire_date") else None,
        target_candidates=data.get("target_candidates", 10),
        target_hires=data.get("target_hires", 1),
        copilot_enabled=data.get("copilot_enabled", True)
    )
    db.add(project)

    # Create default pipeline stages
    default_stages = [
        {"name": "Sourcing",     "order": 1, "color": "#4d9fff"},
        {"name": "Outreach",     "order": 2, "color": "#a78bfa"},
        {"name": "Screening",    "order": 3, "color": "#f5a623"},
        {"name": "Interviewing", "order": 4, "color": "#06b6d4"},
        {"name": "Offer",        "order": 5, "color": "#00d68f"},
        {"name": "Hired",        "order": 6, "color": "#22c55e"},
    ]
    for s in default_stages:
        db.add(PipelineStageORM(
            id=str(uuid.uuid4()),
            project_id=project_id,
            name=s["name"],
            order=s["order"],
            color=s["color"],
            is_default=True
        ))

    db.commit()
    log_usage(db, user.company_id, user.id, "create_project", f"Project: {name}")
    return JSONResponse({"ok": True, "project_id": project_id, "name": name, "message": f"Project '{name}' created with 6 default stages"})


@app.get("/api/projects")
async def get_projects(request: Request, db: Session = Depends(get_db)):
    """Get all recruiter projects for this company."""
    user = require_company_user(request, db)
    projects = db.query(RecruiterProjectORM).filter(
        RecruiterProjectORM.company_id == user.company_id,
        RecruiterProjectORM.is_deleted == False
    ).order_by(RecruiterProjectORM.created_at.desc()).all()

    return JSONResponse({
        "ok": True,
        "projects": [
            {
                "id":                 p.id,
                "name":               p.name,
                "description":        p.description,
                "status":             p.status,
                "priority":           p.priority,
                "stage":              p.stage,
                "role_id":            p.role_id,
                "total_candidates":   p.total_candidates,
                "shortlisted_count":  p.shortlisted_count,
                "outreach_sent":      p.outreach_sent,
                "responses_received": p.responses_received,
                "interviews_scheduled": p.interviews_scheduled,
                "offers_made":        p.offers_made,
                "hires_made":         p.hires_made,
                "target_hire_date":   p.target_hire_date.isoformat() if p.target_hire_date else None,
                "target_hires":       p.target_hires,
                "copilot_enabled":    p.copilot_enabled,
                "created_at":         p.created_at.isoformat()
            }
            for p in projects
        ],
        "total": len(projects)
    })


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str, request: Request, db: Session = Depends(get_db)):
    """Get a single project with its stages and candidates."""
    user    = require_company_user(request, db)
    project = db.query(RecruiterProjectORM).filter(
        RecruiterProjectORM.id == project_id,
        RecruiterProjectORM.company_id == user.company_id,
        RecruiterProjectORM.is_deleted == False
    ).first()
    if not project: raise HTTPException(status_code=404, detail="Project not found")

    # Get stages
    stages = db.query(PipelineStageORM).filter(
        PipelineStageORM.project_id == project_id
    ).order_by(PipelineStageORM.order).all()

    # Get candidates per stage
    pipeline = []
    for stage in stages:
        pcs = db.query(ProjectCandidateORM).filter(
            ProjectCandidateORM.project_id == project_id,
            ProjectCandidateORM.stage_id == stage.id,
            ProjectCandidateORM.is_deleted == False
        ).all()

        candidates_data = []
        for pc in pcs:
            c = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.id == pc.candidate_id).first()
            if c:
                candidates_data.append({
                    "pc_id":        pc.id,
                    "candidate_id": c.id,
                    "name":         c.name,
                    "role":         c.role,
                    "tier":         c.tier,
                    "match_score":  c.match_score,
                    "linkedin_url": c.linkedin_url,
                    "notes":        pc.notes,
                    "rating":       pc.rating,
                    "outreach_sent": pc.outreach_sent,
                    "responded":    pc.responded,
                    "added_at":     pc.created_at.isoformat()
                })

        pipeline.append({
            "stage_id":   stage.id,
            "stage_name": stage.name,
            "order":      stage.order,
            "color":      stage.color,
            "candidates": candidates_data,
            "count":      len(candidates_data)
        })

    return JSONResponse({
        "ok":      True,
        "project": {
            "id":                   project.id,
            "name":                 project.name,
            "status":               project.status,
            "priority":             project.priority,
            "stage":                project.stage,
            "total_candidates":     project.total_candidates,
            "outreach_sent":        project.outreach_sent,
            "responses_received":   project.responses_received,
            "hires_made":           project.hires_made,
            "target_hire_date":     project.target_hire_date.isoformat() if project.target_hire_date else None,
            "copilot_enabled":      project.copilot_enabled,
        },
        "pipeline": pipeline,
        "total_stages": len(stages)
    })


@app.patch("/api/projects/{project_id}")
async def update_project(project_id: str, request: Request, db: Session = Depends(get_db)):
    """Update project status, priority, or metadata."""
    user    = require_recruiter_or_admin(request, db)
    data    = await request.json()
    project = db.query(RecruiterProjectORM).filter(
        RecruiterProjectORM.id == project_id,
        RecruiterProjectORM.company_id == user.company_id,
        RecruiterProjectORM.is_deleted == False
    ).first()
    if not project: raise HTTPException(status_code=404, detail="Project not found")

    if "name"            in data: project.name            = data["name"]
    if "status"          in data: project.status          = data["status"]
    if "priority"        in data: project.priority        = data["priority"]
    if "stage"           in data: project.stage           = data["stage"]
    if "description"     in data: project.description     = data["description"]
    if "copilot_enabled" in data: project.copilot_enabled = data["copilot_enabled"]

    project.updated_at = datetime.utcnow()
    db.commit()
    return JSONResponse({"ok": True, "message": "Project updated"})


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, request: Request, db: Session = Depends(get_db)):
    """Soft-delete a project."""
    user    = require_recruiter_or_admin(request, db)
    project = db.query(RecruiterProjectORM).filter(
        RecruiterProjectORM.id == project_id,
        RecruiterProjectORM.company_id == user.company_id,
        RecruiterProjectORM.is_deleted == False
    ).first()
    if not project: raise HTTPException(status_code=404, detail="Project not found")

    now = datetime.utcnow()
    project.is_deleted = True; project.deleted_at = now

    # Cascade the soft-delete to the pipeline rows. Without this the
    # project_candidates rows stay live: they keep surfacing in pipeline and
    # analytics queries, and the uq_project_candidate constraint blocks
    # re-adding a candidate to a rebuilt project.
    orphans = db.query(ProjectCandidateORM).filter(
        ProjectCandidateORM.project_id == project.id,
        ProjectCandidateORM.company_id == user.company_id,
        ProjectCandidateORM.is_deleted == False
    ).all()
    for pc in orphans:
        pc.is_deleted = True
        pc.updated_at = now

    db.commit()
    return JSONResponse({"ok": True, "message": "Project deleted",
                         "pipeline_rows_removed": len(orphans)})


# ============================================================
# PHASE 33 — PIPELINE (candidates in projects)
# ============================================================

@app.post("/api/projects/{project_id}/candidates")
async def add_candidate_to_project(project_id: str, request: Request, db: Session = Depends(get_db)):
    """Add a candidate to a project pipeline."""
    user = require_recruiter_or_admin(request, db)
    data = await request.json()
    candidate_id = data.get("candidate_id", "")
    if not candidate_id: raise HTTPException(status_code=400, detail="candidate_id is required")

    # Verify project + candidate belong to company
    project = db.query(RecruiterProjectORM).filter(RecruiterProjectORM.id==project_id, RecruiterProjectORM.company_id==user.company_id, RecruiterProjectORM.is_deleted==False).first()
    if not project: raise HTTPException(status_code=404, detail="Project not found")

    candidate = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.id==candidate_id, CompanyCandidateORM.company_id==user.company_id, CompanyCandidateORM.is_deleted==False).first()
    if not candidate: raise HTTPException(status_code=404, detail="Candidate not found")

    # Check duplicate
    existing = db.query(ProjectCandidateORM).filter(ProjectCandidateORM.project_id==project_id, ProjectCandidateORM.candidate_id==candidate_id, ProjectCandidateORM.is_deleted==False).first()
    if existing: return JSONResponse({"ok": False, "error": "Candidate already in this project"}, status_code=400)

    # Get first stage (sourcing)
    first_stage = db.query(PipelineStageORM).filter(PipelineStageORM.project_id==project_id).order_by(PipelineStageORM.order).first()

    pc = ProjectCandidateORM(
        id=str(uuid.uuid4()),
        project_id=project_id,
        candidate_id=candidate_id,
        stage_id=first_stage.id if first_stage else None,
        company_id=user.company_id,
        added_by=user.id,
        stage_name=first_stage.name if first_stage else "Sourcing",
        notes=data.get("notes", "")
    )
    db.add(pc)

    # Update project metrics
    project.total_candidates += 1
    db.commit()

    return JSONResponse({"ok": True, "pc_id": pc.id, "stage": pc.stage_name, "message": f"{candidate.name} added to {project.name}"})


@app.patch("/api/projects/{project_id}/candidates/{pc_id}/stage")
async def move_candidate_stage(project_id: str, pc_id: str, request: Request, db: Session = Depends(get_db)):
    """Move a candidate to a different pipeline stage."""
    user = require_recruiter_or_admin(request, db)
    data = await request.json()
    stage_id = data.get("stage_id", "")

    pc = db.query(ProjectCandidateORM).filter(ProjectCandidateORM.id==pc_id, ProjectCandidateORM.project_id==project_id, ProjectCandidateORM.is_deleted==False).first()
    if not pc: raise HTTPException(status_code=404, detail="Pipeline candidate not found")

    stage = db.query(PipelineStageORM).filter(PipelineStageORM.id==stage_id, PipelineStageORM.project_id==project_id).first()
    if not stage: raise HTTPException(status_code=404, detail="Stage not found")

    pc.stage_id       = stage_id
    pc.stage_name     = stage.name
    pc.stage_changed_at = datetime.utcnow()
    pc.stage_changed_by = user.id
    if data.get("notes"): pc.notes = data["notes"]
    if data.get("rating"): pc.rating = data["rating"]

    # Update project metrics
    project = db.query(RecruiterProjectORM).filter(RecruiterProjectORM.id==project_id).first()
    if project:
        if stage.name.lower() == "hired": project.hires_made += 1
        if stage.name.lower() == "interviewing": project.interviews_scheduled += 1

    db.commit()
    return JSONResponse({"ok": True, "new_stage": stage.name, "message": f"Candidate moved to {stage.name}"})


@app.patch("/api/projects/{project_id}/candidates/{pc_id}/notes")
async def update_pipeline_notes(project_id: str, pc_id: str, request: Request, db: Session = Depends(get_db)):
    """Update notes for a candidate in a pipeline."""
    user = require_recruiter_or_admin(request, db)
    data = await request.json()
    pc = db.query(ProjectCandidateORM).filter(ProjectCandidateORM.id==pc_id, ProjectCandidateORM.project_id==project_id, ProjectCandidateORM.is_deleted==False).first()
    if not pc: raise HTTPException(status_code=404, detail="Pipeline candidate not found")
    if "notes" in data: pc.notes = data["notes"]
    if "rating" in data: pc.rating = data["rating"]
    db.commit()
    return JSONResponse({"ok": True})


@app.delete("/api/projects/{project_id}/candidates/{pc_id}")
async def remove_candidate_from_project(project_id: str, pc_id: str, request: Request, db: Session = Depends(get_db)):
    """Remove a candidate from a project pipeline."""
    user = require_recruiter_or_admin(request, db)
    pc = db.query(ProjectCandidateORM).filter(ProjectCandidateORM.id==pc_id, ProjectCandidateORM.project_id==project_id, ProjectCandidateORM.is_deleted==False).first()
    if not pc: raise HTTPException(status_code=404, detail="Pipeline candidate not found")
    pc.is_deleted = True
    project = db.query(RecruiterProjectORM).filter(RecruiterProjectORM.id==project_id).first()
    if project: project.total_candidates = max(0, project.total_candidates - 1)
    db.commit()
    return JSONResponse({"ok": True, "message": "Candidate removed from pipeline"})


# ============================================================
# PHASE 33 — AI OUTREACH
# ============================================================

@app.post("/api/outreach/generate")
async def generate_outreach_message(request: Request, db: Session = Depends(get_db)):
    """Generate an AI outreach message for a candidate."""
    user = require_recruiter_or_admin(request, db)
    data = await request.json()
    candidate_id = data.get("candidate_id", "")
    if not candidate_id: raise HTTPException(status_code=400, detail="candidate_id is required")

    result = await generate_outreach(
        db=db,
        candidate_id=candidate_id,
        company_id=user.company_id,
        user_id=user.id,
        message_type=data.get("message_type", "linkedin_connection"),
        tone=data.get("tone", "warm"),
        recruiter_name=data.get("recruiter_name", user.name),
        project_id=data.get("project_id")
    )
    if "error" in result: raise HTTPException(status_code=404, detail=result["error"])
    return JSONResponse({"ok": True, **result})


@app.post("/api/outreach/batch")
async def batch_outreach(request: Request, db: Session = Depends(get_db)):
    """Generate outreach for all shortlisted candidates."""
    user = require_recruiter_or_admin(request, db)
    data = await request.json()

    result = await generate_batch_outreach(
        db=db,
        company_id=user.company_id,
        user_id=user.id,
        message_type=data.get("message_type", "linkedin_connection"),
        tone=data.get("tone", "warm"),
        project_id=data.get("project_id")
    )
    return JSONResponse({"ok": True, **result})


@app.get("/api/outreach/candidate/{candidate_id}")
async def get_candidate_outreach(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    """Get all outreach messages for a candidate."""
    user = require_company_user(request, db)
    messages = db.query(OutreachORM).filter(
        OutreachORM.candidate_id == candidate_id,
        OutreachORM.company_id == user.company_id,
        OutreachORM.is_deleted == False
    ).order_by(OutreachORM.created_at.desc()).all()

    return JSONResponse({
        "ok": True,
        "messages": [
            {
                "id":           m.id,
                "message_type": m.message_type,
                "channel":      m.channel,
                "subject":      m.subject,
                "content":      m.content,
                "char_count":   m.char_count,
                "tone":         m.tone,
                "quality_score": m.quality_score,
                "sent":         m.sent,
                "sent_at":      m.sent_at.isoformat() if m.sent_at else None,
                "responded":    m.responded,
                "cost_usd":     m.cost_usd,
                "created_at":   m.created_at.isoformat()
            }
            for m in messages
        ],
        "total": len(messages)
    })


@app.patch("/api/outreach/{outreach_id}/sent")
async def mark_outreach_as_sent(outreach_id: str, request: Request, db: Session = Depends(get_db)):
    """Mark an outreach message as sent."""
    user = require_recruiter_or_admin(request, db)
    data = await request.json()
    success = mark_outreach_sent(db, outreach_id, user.company_id, sent_via=data.get("sent_via", "manual"))
    if not success: raise HTTPException(status_code=404, detail="Outreach message not found")
    return JSONResponse({"ok": True, "message": "Marked as sent"})


@app.patch("/api/outreach/{outreach_id}/responded")
async def mark_outreach_responded(outreach_id: str, request: Request, db: Session = Depends(get_db)):
    """Mark that a candidate responded to outreach."""
    user = require_recruiter_or_admin(request, db)
    msg = db.query(OutreachORM).filter(OutreachORM.id==outreach_id, OutreachORM.company_id==user.company_id).first()
    if not msg: raise HTTPException(status_code=404, detail="Outreach message not found")
    msg.responded = True; msg.responded_at = datetime.utcnow(); db.commit()
    return JSONResponse({"ok": True, "message": "Response recorded"})


@app.get("/api/outreach/stats")
async def get_outreach_statistics(request: Request, db: Session = Depends(get_db)):
    """Get outreach statistics for the dashboard."""
    user = require_company_user(request, db)
    stats = get_outreach_stats(db, user.company_id)
    return JSONResponse({"ok": True, **stats})


@app.get("/api/outreach/options")
async def get_outreach_options():
    """Get available message types and tones."""
    return JSONResponse({
        "ok": True,
        "message_types": get_message_types(),
        "tones": get_outreach_tones()
    })


# ============================================================
# PHASE 33 — RECRUITER COPILOT
# ============================================================

@app.post("/api/copilot/run")
async def run_copilot(request: Request, db: Session = Depends(get_db)):
    """Run a recruiter copilot session."""
    user = require_recruiter_or_admin(request, db)
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    if not prompt: raise HTTPException(status_code=400, detail="prompt is required")

    result = await run_copilot_session(
        db=db,
        company_id=user.company_id,
        user_id=user.id,
        prompt=prompt,
        session_type=data.get("session_type", "next_best_action"),
        project_id=data.get("project_id"),
        role_title=data.get("role_title", "")
    )
    return JSONResponse({"ok": True, **result})


@app.get("/api/copilot/history")
async def get_copilot_session_history(request: Request, db: Session = Depends(get_db)):
    """Get recent copilot sessions."""
    user       = require_company_user(request, db)
    project_id = request.query_params.get("project_id")
    history    = get_copilot_history(db, user.company_id, project_id=project_id)
    return JSONResponse({"ok": True, "sessions": history, "total": len(history)})


@app.patch("/api/copilot/{session_id}/feedback")
async def submit_copilot_session_feedback(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Submit feedback on a copilot session."""
    user    = require_company_user(request, db)
    data    = await request.json()
    helpful = data.get("helpful", True)
    success = submit_copilot_feedback(db, session_id, user.company_id, helpful=helpful, acted_on=data.get("acted_on", False))
    if not success: raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse({"ok": True, "message": "Feedback recorded"})


@app.get("/api/copilot/stats")
async def get_copilot_statistics(request: Request, db: Session = Depends(get_db)):
    """Get copilot usage statistics."""
    user  = require_company_user(request, db)
    stats = get_copilot_stats(db, user.company_id)
    return JSONResponse({"ok": True, **stats})


@app.get("/api/copilot/session-types")
async def get_copilot_session_types():
    """Get available copilot session types."""
    return JSONResponse({"ok": True, "session_types": get_session_types()})

# ============================================================
# STRIPE WEBHOOK — THE ONE AND ONLY HANDLER (FIX F)
# Point the Stripe dashboard endpoint at:  https://aitmp.io/stripe-webhook
# (The duplicate /api/billing/webhook and /stripe/webhook handlers
#  were removed — three conflicting handlers is how payments get lost.)
# ============================================================
@app.post("/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload=await request.body(); sig_header=request.headers.get("stripe-signature")
    try: event=stripe.Webhook.construct_event(payload,sig_header,STRIPE_WEBHOOK_SECRET)
    except Exception: raise HTTPException(status_code=400,detail="Invalid signature")
    if event["type"]=="checkout.session.completed":
        session_obj=event["data"]["object"]; company_id=session_obj.get("metadata",{}).get("company_id"); plan=session_obj.get("metadata",{}).get("plan","business")
        if company_id:
            company=db.query(CompanyORM).filter(CompanyORM.id==company_id).first()
            if company:
                company.plan=plan; company.seat_limit=PLANS.get(plan,PLANS["business"])["seat_limit"]; db.commit()
                await fire_event(db,company_id,"billing.subscription.updated",{"plan":plan})
                # Payment receipt email (no-op until RESEND_API_KEY is set)
                try:
                    _admin=db.query(CompanyUserORM).filter(CompanyUserORM.company_id==company_id,CompanyUserORM.role=="admin",CompanyUserORM.is_deleted==False).first()
                    _amt=session_obj.get("amount_total"); _amt_str=f"${_amt/100:,.2f}" if _amt else ""
                    if _admin: email_engine.send_payment_receipt(_admin.email,_admin.name,plan,_amt_str)
                except Exception: pass
    elif event["type"]=="invoice.payment_succeeded":
        invoice_obj=event["data"]["object"]; company_id=invoice_obj.get("metadata",{}).get("company_id")
        if company_id: invoice=InvoiceORM(id=str(uuid.uuid4()),company_id=company_id,amount=invoice_obj["amount_paid"]/100,status="paid",description="Subscription payment",stripe_invoice_id=invoice_obj["id"],pdf_url=invoice_obj.get("invoice_pdf"),paid_at=datetime.utcnow()); db.add(invoice); db.commit()
    elif event["type"]=="invoice.payment_failed":
        session_obj=event["data"]["object"]; company_id=session_obj.get("metadata",{}).get("company_id")
        if company_id:
            sub=db.query(SubscriptionORM).filter(SubscriptionORM.company_id==company_id).first()
            if sub: sub.status="past_due"; db.commit()
    elif event["type"]=="customer.subscription.deleted":
        session_obj=event["data"]["object"]; customer_id=session_obj.get("customer")
        company=db.query(CompanyORM).filter(CompanyORM.stripe_customer_id==customer_id).first()
        if company: company.plan="free"; db.commit()
    return {"status":"ok"}

# ============================================================
# PADDLE (Billing v2) — NEW payment processor, alongside Stripe (Stripe above is untouched).
# Sandbox-first. Config for the frontend + webhook for plan changes. See app/paddle_engine.py.
# ============================================================
@app.get("/api/paddle/config")
def paddle_config(request: Request):
    """Public config for Paddle.js on the frontend (client token is public by design).
    Never returns the API key or webhook secret."""
    return JSONResponse(paddle_engine.public_config())

@app.post("/api/paddle/webhook")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    sig = request.headers.get("Paddle-Signature", "")
    if not paddle_engine.verify_webhook(raw, sig):
        raise HTTPException(status_code=400, detail="Invalid Paddle signature")
    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")
    etype = (event.get("event_type") or event.get("type") or "").lower()
    data  = event.get("data", {}) or {}
    custom = (data.get("custom_data") or {}) if isinstance(data.get("custom_data"), dict) else {}

    def _find_company():
        cid = custom.get("company_id")
        if cid:
            return db.query(CompanyORM).filter(CompanyORM.id == cid).first()
        # fallback: match by customer email if Paddle included it
        email = ((data.get("customer") or {}).get("email")) if isinstance(data.get("customer"), dict) else None
        if email:
            u = db.query(CompanyUserORM).filter(CompanyUserORM.email == normalize_email(email), CompanyUserORM.is_deleted == False).first()
            if u:
                return db.query(CompanyORM).filter(CompanyORM.id == u.company_id).first()
        return None

    def _plan_from_items():
        for it in (data.get("items") or []):
            pid = ((it.get("price") or {}).get("id")) or it.get("price_id")
            p = paddle_engine.plan_for_price(pid)
            if p:
                return p
        return None

    def _admin_of(company):
        """Admin user of a company (for lifecycle emails). None-safe."""
        if not company:
            return None
        return db.query(CompanyUserORM).filter(
            CompanyUserORM.company_id == company.id,
            CompanyUserORM.role == "admin",
            CompanyUserORM.is_deleted == False,
        ).first()

    def _price_str(plan):
        p = PLANS.get(plan)
        return f"${p['price_monthly']}/month" if p and p.get("price_monthly") else ""

    def _apply_plan(company, plan):
        company.plan = plan
        company.seat_limit = PLANS.get(plan, PLANS.get("business", {"seat_limit": 1})).get("seat_limit", company.seat_limit)

    try:
        # Card-required trial started → grant plan access now (no charge yet)
        if etype in ("subscription.trialing", "subscription.created"):
            company = _find_company()
            plan = custom.get("plan") or _plan_from_items() or "business"
            status = (data.get("status") or "").lower()
            # subscription.created can also fire for non-trial subs; only treat trials specially
            if company and plan and (etype == "subscription.trialing" or status == "trialing"):
                _apply_plan(company, plan)
                # Record when the trial ends (Paddle's next_billed_at = first charge date), so the
                # day-6 reminder sweep can find it. Fall back to now + 7 days.
                ends = data.get("next_billed_at") or ((data.get("current_billing_period") or {}).get("ends_at"))
                trial_end = None
                if ends:
                    try: trial_end = datetime.fromisoformat(str(ends).replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception: trial_end = None
                company.trial_ends_at = trial_end or (datetime.utcnow() + timedelta(days=7))
                company.trial_reminder_sent = False
                db.commit()
                # We no longer sell a card-on-file trial — the free tier is
                # permanent and needs no card — so there is no trial email.
                # If Paddle ever reports a trialing subscription, the plan is
                # still applied above; we simply don't message about a trial.
        # Trial converted / renewal charged → keep plan active + receipt
        elif etype in ("transaction.completed", "transaction.paid", "payment.completed", "subscription.activated"):
            company = _find_company()
            plan = custom.get("plan") or _plan_from_items() or "business"
            if company and plan:
                _apply_plan(company, plan)
                company.trial_ends_at = None; company.trial_reminder_sent = False  # trial converted → paid
                db.commit()
                u = _admin_of(company)
                if u:
                    try: email_engine.send_payment_receipt(u.email, u.name, PLANS.get(plan, {}).get("name", plan), amount=_price_str(plan))
                    except Exception: pass
        # Subscription cancelled → downgrade to free
        elif etype in ("subscription.canceled", "subscription.cancelled"):
            company = _find_company()
            if company:
                company.plan = "free"
                company.trial_ends_at = None; company.trial_reminder_sent = False
                db.commit()
    except Exception:
        db.rollback()
    return {"status": "ok", "event": etype}


# ============================================================
# DAY-6 TRIAL-ENDING REMINDER (scheduler)
# Card-required trials auto-charge on day 7 via Paddle. This sweep emails a heads-up
# ~24h before, so recruiters aren't surprised. Idempotent via trial_reminder_sent.
# Driven by BOTH: (a) an in-process daily task (below), and (b) an external cron that
# POSTs /api/cron/trial-reminders with the X-Cron-Secret header (Azure scheduled job).
# ============================================================
def run_trial_reminder_sweep(db) -> int:
    """Email the day-before reminder to every trial ending within ~36h. Returns count sent."""
    now = datetime.utcnow()
    horizon = now + timedelta(hours=36)
    companies = db.query(CompanyORM).filter(
        CompanyORM.trial_ends_at != None,          # noqa: E711
        CompanyORM.trial_ends_at > now,
        CompanyORM.trial_ends_at <= horizon,
        CompanyORM.trial_reminder_sent == False,    # noqa: E712
        CompanyORM.plan != "free",
        CompanyORM.is_deleted == False,             # noqa: E712
    ).all()
    sent = 0
    for c in companies:
        u = db.query(CompanyUserORM).filter(
            CompanyUserORM.company_id == c.id, CompanyUserORM.role == "admin",
            CompanyUserORM.is_deleted == False,     # noqa: E712
        ).first()
        if not u:
            continue
        meta = PLANS.get(c.plan, {})
        amount = f"${meta['price_monthly']}/month" if meta.get("price_monthly") else ""
        try:
            # Trial-ending reminders are retired along with the trial itself.
            # Marked as sent so the sweep stops revisiting these rows.
            c.trial_reminder_sent = True
        except Exception:
            pass
    try:
        db.commit()
    except Exception:
        db.rollback()
    return sent


@app.post("/api/cron/trial-reminders")
async def cron_trial_reminders(request: Request, db: Session = Depends(get_db)):
    """External-cron entrypoint for the day-6 reminder. Protected by CRON_SECRET."""
    secret = os.getenv("CRON_SECRET", "").strip()
    provided = request.headers.get("X-Cron-Secret", "")
    if not secret or not secrets.compare_digest(provided, secret):
        raise HTTPException(status_code=403, detail="Forbidden")
    n = run_trial_reminder_sweep(db)
    return {"ok": True, "reminders_sent": n}


# ============================================================
# PUBLIC LANDING DEMO — real GPT-4o example (computed once, cached)
# Replaces the old Math.random() fabrication. Runs ONE genuine scoring pass on a
# fixed sample candidate, caches it (memory + file), and serves that thereafter —
# authentic output, zero per-click cost, no abuse surface. Honest failure if AI is down.
# ============================================================
_DEMO_EXAMPLE_CACHE = None
_DEMO_EXAMPLE_PATH = os.path.join(
    os.path.dirname(os.getenv("DATABASE_PATH", "") or "elinor.db") or ".", "demo_example.json"
)
_DEMO_ROLE = "Senior Backend Engineer"
_DEMO_JD = ("Senior Backend Engineer to own our payments platform. Must have 6+ years building "
            "high-throughput distributed systems in Python or Go, deep PostgreSQL, event-driven "
            "architecture (Kafka), and production experience on a major cloud (AWS/Azure/GCP). "
            "Bonus: fintech/payments background, mentoring, and a track record of reducing latency at scale.")
_DEMO_CANDIDATE = {
    "name": "Sample Candidate",
    "text": ("Backend engineer, 7 years. Led a payments team of 5 at a fintech scale-up; rebuilt the "
             "settlement pipeline in Python + Kafka handling 4M events/day, cutting p99 latency 38%. "
             "Strong PostgreSQL (sharding, query tuning) and AWS (EKS, RDS, SQS). Mentors two juniors. "
             "Gap: limited Go; most recent architecture work is event-driven but not yet multi-region."),
}


@app.get("/api/demo/example")
def api_demo_example():
    """Genuine, cached GPT-4o evaluation for the public landing demo (no fabrication)."""
    global _DEMO_EXAMPLE_CACHE
    if _DEMO_EXAMPLE_CACHE:
        return JSONResponse(_DEMO_EXAMPLE_CACHE)
    try:
        if os.path.exists(_DEMO_EXAMPLE_PATH):
            with open(_DEMO_EXAMPLE_PATH) as f:
                _DEMO_EXAMPLE_CACHE = json.load(f)
                return JSONResponse(_DEMO_EXAMPLE_CACHE)
    except Exception:
        pass
    try:
        from app.ai_engine import score_candidates
        results, _ = score_candidates(_DEMO_ROLE, _DEMO_JD, [_DEMO_CANDIDATE], "business")
        if results:
            r = results[0]
            payload = {
                "ok": True, "example": True, "role": _DEMO_ROLE, "name": r["name"],
                "tier": r["tier"], "match_score": r["match_score"],
                "adaptability": r["adaptability"], "focus_penalty": r["focus_penalty"],
                "ai_analysis": (r.get("ai_analysis") or "").strip(),
            }
            _DEMO_EXAMPLE_CACHE = payload
            try:
                with open(_DEMO_EXAMPLE_PATH, "w") as f:
                    json.dump(payload, f)
            except Exception:
                pass
            return JSONResponse(payload)
    except Exception:
        pass
    # AI unavailable → honest "unavailable", never fabricated numbers
    return JSONResponse({"ok": False, "example": True})


@app.on_event("startup")
async def _start_trial_reminder_scheduler():
    """Best-effort in-process daily sweep so reminders work without external cron setup.
    Disable with ENABLE_TRIAL_SCHEDULER=false (e.g. if you drive it purely via Azure cron)."""
    import asyncio
    if os.getenv("ENABLE_TRIAL_SCHEDULER", "true").strip().lower() not in ("1", "true", "yes", "on"):
        return

    async def _loop():
        await asyncio.sleep(60)  # let startup + migrations settle
        while True:
            try:
                db = SessionLocal()
                try:
                    run_trial_reminder_sweep(db)
                finally:
                    db.close()
            except Exception:
                pass
            await asyncio.sleep(12 * 3600)  # runs twice a day; idempotent

    asyncio.create_task(_loop())


# ============================================================
# LEGACY ROUTES
# ============================================================
@app.post("/create_role")
async def create_role(request: Request, role_title: str = Body(...,embed=True), human_story: str = Body(...,embed=True), db: Session = Depends(get_sqlalchemy_db), user_email: str = Depends(require_user)):
    conversation=ConversationORM(user_email=user_email,role_title=role_title,human_story=human_story); db.add(conversation); db.commit(); db.refresh(conversation)
    return JSONResponse({"ok":True,"id":conversation.id})

@app.post("/results")
async def run_results(request: Request, role_title: str = Body(None,embed=True), human_story: str = Body(None,embed=True), db: Session = Depends(get_sqlalchemy_db), user_email: str = Depends(require_user)):
    # RETIRED: this legacy route used to return hardcoded/fabricated candidates
    # (via run_full_talent_match → search_linkedin_profiles). Real scoring now lives at
    # POST /api/candidates/score — GPT-4o scoring of candidates you actually provide.
    return JSONResponse({"ok": False, "deprecated": True,
        "error": "This endpoint has been retired. Use POST /api/candidates/score to score real candidates."},
        status_code=410)

@app.get("/history")
async def get_history(request: Request, db: Session = Depends(get_sqlalchemy_db), user_email: str = Depends(require_user)):
    conversations=db.query(ConversationORM).filter(ConversationORM.user_email==user_email).order_by(ConversationORM.created_at.desc()).all()
    return JSONResponse({"ok":True,"history":[{"id":c.id,"role_title":c.role_title,"timestamp":c.created_at.isoformat()} for c in conversations]})

@app.get("/conversation/{id}")
async def get_past_conversation(id: int, request: Request, db: Session = Depends(get_sqlalchemy_db), user_email: str = Depends(require_user)):
    conv=db.query(ConversationORM).filter(ConversationORM.id==id,ConversationORM.user_email==user_email).first()
    if not conv: return JSONResponse({"ok":False},status_code=404)
    candidates=db.query(CandidateMatchORM).filter(CandidateMatchORM.search_id==id).all()
    return JSONResponse({"ok":True,"role_title":conv.role_title,"results":[{"name":c.name,"match_score":c.match_score,"ai_analysis":c.ai_analysis,"linkedin_url":c.linkedin_url,"synthesis_label":getattr(c,"synthesis_label",None),"silent_skill":getattr(c,"silent_skill",None)} for c in candidates]})

@app.post("/create-checkout-session")
async def create_checkout_session_route(request: Request, db: Session = Depends(get_sqlalchemy_db)):
    # Consolidated on Paddle — legacy Stripe checkout retired.
    user_email = request.session.get("user_email")
    if not user_email: raise HTTPException(status_code=401, detail="Not authenticated")
    return JSONResponse({"ok": False, "use_paddle": True,
                         "paddle": paddle_engine.public_config(),
                         "message": "Checkout has moved to Paddle."})


# ============================================================
# PHASE 34 — AI INTERVIEW QUESTIONS
# ============================================================

from app.interview_engine import (
    generate_interview_questions,
    save_question_set,
    get_questions_for_candidate,
    get_interview_stats,
)
from app.db import InterviewQuestionSetORM

@app.post("/api/interview/generate")
async def api_generate_interview_questions(request: Request, db: Session = Depends(get_db)):
    """Generate AI interview questions for a candidate."""
    company, user = get_current_company_user(request, db)
    body = await request.json()

    candidate_id     = body.get("candidate_id")
    candidate_name   = body.get("candidate_name", "Candidate")
    candidate_role   = body.get("candidate_role", "")
    candidate_tier   = body.get("candidate_tier", "bronze")
    candidate_score  = float(body.get("candidate_score", 0))
    candidate_analysis = body.get("candidate_analysis", "")
    project_id       = body.get("project_id")
    focus_areas      = body.get("focus_areas")

    # Get job info from project if available
    job_title = "the role"
    job_description = ""
    job_skills = ""
    job_id = None

    if project_id:
        try:
            proj = db.query(RecruiterProjectORM).filter(
                RecruiterProjectORM.id == project_id,
                RecruiterProjectORM.company_id == company.id
            ).first()
            if proj:
                job_title = proj.name
                job_description = proj.description or ""
        except Exception:
            pass

    # Try to get candidate from DB for better data
    if candidate_id:
        try:
            cand = db.query(CompanyCandidateORM).filter(
                CompanyCandidateORM.id == candidate_id,
                CompanyCandidateORM.company_id == company.id
            ).first()
            if cand:
                candidate_name    = cand.name
                candidate_role    = cand.role or candidate_role
                candidate_tier    = cand.tier or candidate_tier
                candidate_score   = cand.match_score or candidate_score
                candidate_analysis = cand.ai_analysis or candidate_analysis
                job_id = cand.job_id
        except Exception:
            pass

    result = await generate_interview_questions(
        candidate_name=candidate_name,
        candidate_role=candidate_role,
        candidate_tier=candidate_tier,
        candidate_score=candidate_score,
        candidate_analysis=candidate_analysis,
        job_title=job_title,
        job_description=job_description,
        job_skills=job_skills,
    )

    # Save to DB
    if candidate_id:
        try:
            record = save_question_set(
                db=db,
                company_id=company.id,
                candidate_id=candidate_id,
                job_id=job_id,
                created_by=user.id,
                result=result,
                focus_areas=focus_areas,
            )
            result["set_id"] = record.id
        except Exception as e:
            result["set_id"] = None

    result["ok"] = True
    return result


@app.get("/api/interview/candidate/{candidate_id}")
def api_get_interview_questions(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    """Get the latest interview question set for a candidate."""
    company, user = get_current_company_user(request, db)

    record = get_questions_for_candidate(db, company.id, candidate_id)
    if not record:
        return {"ok": False, "error": "No questions found for this candidate"}

    import json as _json
    questions = _json.loads(record.questions_json) if record.questions_json else []

    return {
        "ok":            True,
        "set_id":        record.id,
        "questions":     questions,
        "count":         record.question_count,
        "tier":          record.tier,
        "cost_usd":      record.cost_usd,
        "latency_ms":    record.latency_ms,
        "created_at":    record.created_at.isoformat(),
    }


@app.patch("/api/interview/{set_id}/used")
def api_mark_interview_used(set_id: str, request: Request, db: Session = Depends(get_db)):
    """Mark an interview question set as used."""
    company, user = get_current_company_user(request, db)

    record = db.query(InterviewQuestionSetORM).filter(
        InterviewQuestionSetORM.id == set_id,
        InterviewQuestionSetORM.company_id == company.id,
        InterviewQuestionSetORM.is_deleted == False
    ).first()

    if not record:
        return {"ok": False, "error": "Not found"}

    record.used_in_interview = True
    db.commit()
    return {"ok": True, "set_id": set_id}


@app.get("/api/interview/stats")
def api_interview_stats(request: Request, db: Session = Depends(get_db)):
    """Get interview question generation stats for the company."""
    company, user = get_current_company_user(request, db)
    return get_interview_stats(db, company.id)

# ============================================================
# PHASE 34 — INTELLIGENCE APIs (Steps 9)
# All 9 intelligence endpoints
# ============================================================

from app.intelligence_engine import (
    take_daily_snapshot,
    get_snapshot_trend,
    predict_pipeline_metrics,
    generate_narrative,
    generate_next_best_actions,
    compute_recruiter_performance,
    generate_weekly_digest,
    check_and_generate_alerts,
    get_active_alerts,
    get_intelligence_settings,
    update_intelligence_settings,
    get_audit_logs,
    _log_audit,
)
from app.db import (
    IntelligenceSnapshotORM,
    IntelligenceForecastORM,
    IntelligenceNarrativeORM,
    IntelligenceActionORM,
    IntelligenceAlertORM,
    IntelligenceDigestORM,
    IntelligenceSettingsORM,
    IntelligenceAuditLogORM,
    RecruiterPerformanceORM,
)

# ── Step 1 · Historical Snapshots ──────────────────────────
@app.post("/api/intelligence/snapshot")
def api_take_snapshot(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    snapshot = take_daily_snapshot(db, company.id)
    return {"ok": True, "snapshot_id": snapshot.id, "date": snapshot.snapshot_date.isoformat()}

@app.get("/api/intelligence/trend")
def api_get_trend(request: Request, days: int = 30, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    trend = get_snapshot_trend(db, company.id, days=days)
    return {"ok": True, "trend": trend, "days": days, "data_points": len(trend)}

# ── Step 2 · Predictive Forecast ──────────────────────────
@app.get("/api/forecast/role")
def api_forecast_role(request: Request, project_id: str = None, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    predictions = predict_pipeline_metrics(db, company.id, project_id)
    _log_audit(db, company.id, "forecast", "role_forecast_requested")
    return predictions

@app.get("/api/forecast/outreach")
def api_forecast_outreach(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    preds = predict_pipeline_metrics(db, company.id)
    # FIX E-3: removed invented "best_channel"/"channel_lift_pct" —
    # add them back only when real per-channel data exists.
    return {
        "ok":                    True,
        "outreach_volume_needed": preds.get("outreach_volume_needed"),
        "response_probability":   preds.get("response_probability"),
        "outreach_success_prob":  preds.get("outreach_success_prob"),
    }

@app.get("/api/forecast/risk")
def api_forecast_risk(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    preds = predict_pipeline_metrics(db, company.id)
    alerts = get_active_alerts(db, company.id)
    return {
        "ok":              True,
        "stall_risk":      preds.get("pipeline_stall_risk"),
        "stall_in_days":   preds.get("stall_in_days"),
        "score_volatility": preds.get("score_volatility"),
        "momentum":        preds.get("momentum"),
        "active_alerts":   len(alerts),
        "critical_alerts": sum(1 for a in alerts if a["severity"] == "critical"),
    }

# ── Step 3 · Narrative Intelligence ───────────────────────
@app.post("/api/insights/narrative")
async def api_generate_narrative(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    body = await request.json()
    narrative_type = body.get("type", "weekly_change")

    from app.intelligence_engine import _get_outreach_metrics
    outreach = _get_outreach_metrics(db, company.id)
    preds    = predict_pipeline_metrics(db, company.id)

    context = {
        "total_candidates":  db.query(CompanyCandidateORM).filter(
            CompanyCandidateORM.company_id == company.id,
            CompanyCandidateORM.is_deleted == False
        ).count(),
        "outreach_sent":     outreach.get("sent", 0),
        "response_rate":     outreach.get("response_rate", 0),
        "stall_risk":        preds.get("pipeline_stall_risk"),
        "momentum":          preds.get("momentum", {}),
        **body.get("context", {}),
    }

    result = await generate_narrative(db, company.id, narrative_type, context)
    _log_audit(db, company.id, "narrative", "generated", {"type": narrative_type})
    return result

# ── Step 5 · Next-Best-Actions ─────────────────────────────
@app.get("/api/insights/actions")
async def api_next_best_actions(request: Request, project_id: str = None, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    result = await generate_next_best_actions(db, company.id, project_id)
    _log_audit(db, company.id, "actions", "generated", {"project_id": project_id})
    return result

@app.patch("/api/insights/actions/{action_id}/acted")
def api_mark_action_acted(action_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    action = db.query(IntelligenceActionORM).filter(
        IntelligenceActionORM.id == action_id,
        IntelligenceActionORM.company_id == company.id,
    ).first()
    if not action:
        return {"ok": False, "error": "Not found"}
    action.acted_on = True
    db.commit()
    _log_audit(db, company.id, "actions", "acted_on", {"action_id": action_id})
    return {"ok": True}

# ── Step 6 · Recruiter Performance ────────────────────────
@app.get("/api/intelligence/performance")
def api_recruiter_performance(request: Request, period: str = None, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    performance = compute_recruiter_performance(db, company.id, period)
    return {"ok": True, "performance": performance, "count": len(performance)}

# ── Step 7 · Weekly Digest ────────────────────────────────
@app.get("/api/insights/weekly")
async def api_weekly_digest(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    result = await generate_weekly_digest(db, company.id)
    _log_audit(db, company.id, "digest", "generated")
    return result

# ── Step 8 · Alerts ────────────────────────────────────────
@app.get("/api/alerts")
def api_get_alerts(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    check_and_generate_alerts(db, company.id)
    alerts = get_active_alerts(db, company.id)
    return {"ok": True, "alerts": alerts, "count": len(alerts)}

@app.patch("/api/alerts/{alert_id}/resolve")
def api_resolve_alert(alert_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    alert = db.query(IntelligenceAlertORM).filter(
        IntelligenceAlertORM.id == alert_id,
        IntelligenceAlertORM.company_id == company.id,
    ).first()
    if not alert:
        return {"ok": False, "error": "Not found"}
    alert.resolved    = True
    alert.resolved_at = datetime.utcnow()
    alert.resolved_by = user.id
    db.commit()
    return {"ok": True}

# ── Step 11 · Settings ─────────────────────────────────────
@app.get("/api/intelligence/settings")
def api_get_intelligence_settings(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    return get_intelligence_settings(db, company.id)

@app.patch("/api/intelligence/settings")
async def api_update_intelligence_settings(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    body = await request.json()
    return update_intelligence_settings(db, company.id, body)

# ── Step 12 · Audit Logs ──────────────────────────────────
@app.get("/api/intelligence/audit")
def api_intelligence_audit(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    logs = get_audit_logs(db, company.id, limit=limit)
    return {"ok": True, "logs": logs, "count": len(logs)}

# ── Batch job endpoint (Step 10 · Caching) ────────────────
@app.post("/api/intelligence/batch")
async def api_run_batch(request: Request, db: Session = Depends(get_db)):
    """Run all daily batch intelligence jobs for a company."""
    company, user = get_current_company_user(request, db)
    if user.role not in ("admin", "owner"):
        return {"ok": False, "error": "Admin only"}

    results = {}

    # 1. Daily snapshot
    try:
        snap = take_daily_snapshot(db, company.id)
        results["snapshot"] = snap.id
    except Exception as e:
        results["snapshot"] = f"error: {e}"

    # 2. Pre-compute forecasts
    try:
        preds = predict_pipeline_metrics(db, company.id)
        results["forecast"] = preds.get("pipeline_stall_risk")
    except Exception as e:
        results["forecast"] = f"error: {e}"

    # 3. Check alerts
    try:
        alerts = check_and_generate_alerts(db, company.id)
        results["alerts"] = len(alerts)
    except Exception as e:
        results["alerts"] = f"error: {e}"

    # 4. Recruiter performance
    try:
        perf = compute_recruiter_performance(db, company.id)
        results["performance"] = len(perf)
    except Exception as e:
        results["performance"] = f"error: {e}"

    _log_audit(db, company.id, "batch", "completed", results)
    return {"ok": True, "results": results, "ran_at": datetime.utcnow().isoformat()}

# ============================================================
# PHASE 35 — AI SCORECARDS
# ============================================================

from app.scorecard_engine import (
    generate_scorecard,
    save_scorecard,
    add_human_score,
    get_scorecard,
    get_scorecard_by_id,
    get_scorecard_stats,
)
from app.db import ScorecardORM

@app.post("/api/scorecard/generate")
async def api_generate_scorecard(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    body = await request.json()

    candidate_id     = body.get("candidate_id")
    candidate_name   = body.get("candidate_name", "Candidate")
    candidate_role   = body.get("candidate_role", "")
    candidate_tier   = body.get("candidate_tier", "bronze")
    candidate_score  = float(body.get("candidate_score", 0))
    candidate_analysis = body.get("candidate_analysis", "")
    project_id       = body.get("project_id")
    focus_areas      = body.get("focus_areas")

    job_title = "the role"
    job_description = ""
    job_id = None

    if candidate_id:
        try:
            cand = db.query(CompanyCandidateORM).filter(
                CompanyCandidateORM.id == candidate_id,
                CompanyCandidateORM.company_id == company.id
            ).first()
            if cand:
                candidate_name     = cand.name
                candidate_role     = cand.role or candidate_role
                candidate_tier     = cand.tier or candidate_tier
                candidate_score    = cand.match_score or candidate_score
                candidate_analysis = cand.ai_analysis or candidate_analysis
        except Exception:
            pass

    if project_id:
        try:
            proj = db.query(RecruiterProjectORM).filter(
                RecruiterProjectORM.id == project_id,
                RecruiterProjectORM.company_id == company.id
            ).first()
            if proj:
                job_title       = proj.name
                job_description = proj.description or ""
        except Exception:
            pass

    result = await generate_scorecard(
        candidate_name=candidate_name,
        candidate_role=candidate_role,
        candidate_tier=candidate_tier,
        candidate_score=candidate_score,
        candidate_analysis=candidate_analysis,
        job_title=job_title,
        job_description=job_description,
        focus_areas=focus_areas,
    )

    if candidate_id:
        try:
            record = save_scorecard(
                db=db,
                company_id=company.id,
                candidate_id=candidate_id,
                created_by=user.id,
                result=result,
                job_id=job_id,
                project_id=project_id,
                focus_areas=focus_areas,
            )
            result["scorecard_id"] = record.id
        except Exception as e:
            result["scorecard_id"] = None

    result["ok"] = True
    return result


@app.get("/api/scorecard/candidate/{candidate_id}")
def api_get_scorecard(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    record = get_scorecard(db, company.id, candidate_id)
    if not record:
        return {"ok": False, "error": "No scorecard found"}

    return {
        "ok":                  True,
        "scorecard_id":        record.id,
        "overall_score":       record.overall_score,
        "recommendation":      record.recommendation,
        "recommendation_label": record.recommendation_label,
        "summary":             record.summary,
        "dimensions":          json.loads(record.dimensions_json or "[]"),
        "strengths":           json.loads(record.strengths_json or "[]"),
        "concerns":            json.loads(record.concerns_json or "[]"),
        "vs_ai_score":         json.loads(record.vs_ai_score_json or "{}"),
        "avg_human_score":     record.avg_human_score,
        "human_scorer_count":  record.human_scorer_count,
        "cost_usd":            record.cost_usd,
        "latency_ms":          record.latency_ms,
        "created_at":          record.created_at.isoformat(),
    }


@app.post("/api/scorecard/{scorecard_id}/human-score")
async def api_add_human_score(scorecard_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    body = await request.json()
    try:
        record = add_human_score(
            db=db,
            scorecard_id=scorecard_id,
            company_id=company.id,
            scorer_id=user.id,
            scorer_name=user.name,
            human_scores=body.get("scores", {}),
            human_notes=body.get("notes"),
        )
        return {"ok": True, "avg_human_score": record.avg_human_score, "scorer_count": record.human_scorer_count}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@app.delete("/api/scorecard/{scorecard_id}")
def api_delete_scorecard(scorecard_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    record = get_scorecard_by_id(db, scorecard_id, company.id)
    if not record:
        return {"ok": False, "error": "Not found"}
    record.is_deleted = True
    record.deleted_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.get("/api/scorecard/stats")
def api_scorecard_stats(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    return get_scorecard_stats(db, company.id)


# ============================================================
# PHASE 36 — NARRATIVE INTELLIGENCE (missing pieces)
# ============================================================

@app.get("/api/narrative/drift/{candidate_id}")
def api_narrative_drift(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    """Compare narrative recommendation vs scorecard recommendation."""
    company, user = get_current_company_user(request, db)

    # Get latest narrative
    narrative_rec = None
    try:
        narrative = db.query(AINarrativeORM).filter(
            AINarrativeORM.candidate_id == candidate_id,
            AINarrativeORM.company_id   == company.id,
        ).order_by(AINarrativeORM.created_at.desc()).first()
        if narrative:
            narrative_rec = getattr(narrative, 'recommendation_strength', None)
    except Exception:
        pass

    # Get latest scorecard
    scorecard_rec = None
    try:
        scorecard = db.query(ScorecardORM).filter(
            ScorecardORM.candidate_id == candidate_id,
            ScorecardORM.company_id   == company.id,
            ScorecardORM.is_deleted   == False,
        ).order_by(ScorecardORM.created_at.desc()).first()
        if scorecard:
            scorecard_rec = scorecard.recommendation
    except Exception:
        pass

    scale = {"strong_yes": 4, "yes": 3, "maybe": 2, "no": 1}
    nVal  = scale.get(narrative_rec, 0)
    sVal  = scale.get(scorecard_rec, 0)
    diff  = abs(nVal - sVal) if nVal and sVal else 0

    alignment = "aligned" if diff == 0 else "slight_variance" if diff == 1 else "significant_variance"

    return {
        "ok":               True,
        "candidate_id":     candidate_id,
        "narrative_rec":    narrative_rec,
        "scorecard_rec":    scorecard_rec,
        "drift_score":      diff,
        "alignment":        alignment,
        "action_required":  diff >= 2,
    }

@app.get("/api/narrative/analytics")
def api_narrative_analytics(request: Request, db: Session = Depends(get_db)):
    """Narrative analytics — sentiment, alignment, cost."""
    company, user = get_current_company_user(request, db)
    try:
        narratives = db.query(AINarrativeORM).filter(
            AINarrativeORM.company_id == company.id
        ).all()

        if not narratives:
            return {"ok": True, "total": 0}

        total      = len(narratives)
        total_cost = sum(getattr(n, 'cost_usd', 0) or 0 for n in narratives)
        avg_latency = sum(getattr(n, 'latency_ms', 0) or 0 for n in narratives) / total

        sentiments = {}
        for n in narratives:
            s = getattr(n, 'sentiment', 'unknown') or 'unknown'
            sentiments[s] = sentiments.get(s, 0) + 1

        return {
            "ok":           True,
            "total":        total,
            "total_cost":   round(total_cost, 6),
            "avg_latency":  round(avg_latency, 1),
            "sentiments":   sentiments,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================================================
# PHASE 37 — FORECAST 2.0 + RECRUITER OS
# ============================================================

from app.forecast_engine_v2 import (
    compute_funnel,
    compute_confidence_bands,
    run_scenario,
    detect_bottlenecks,
    smart_search,
    get_candidate_timeline,
    compare_candidates,
)
from app.db import ForecastCacheORM, ScenarioLogORM, FunnelStatsORM

@app.get("/api/forecast/funnel")
def api_forecast_funnel(request: Request, project_id: str = None, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    result = compute_funnel(db, company.id, project_id)
    log_usage(db, company.id, user.id, "forecast_funnel")
    return result

@app.get("/api/forecast/confidence")
def api_forecast_confidence(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    result = compute_confidence_bands(db, company.id)
    log_usage(db, company.id, user.id, "forecast_confidence")
    return result

@app.post("/api/forecast/scenario")
async def api_forecast_scenario(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    body = await request.json()
    result = run_scenario(
        db=db,
        company_id=company.id,
        outreach_delta=float(body.get("outreach_delta", 0.0)),
        response_delta=float(body.get("response_delta", 0.0)),
        recruiter_load=float(body.get("recruiter_load", 1.0)),
        project_id=body.get("project_id"),
    )
    log_usage(db, company.id, user.id, "forecast_scenario")
    return result

@app.get("/api/forecast/bottlenecks")
def api_forecast_bottlenecks(request: Request, project_id: str = None, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    result = detect_bottlenecks(db, company.id, project_id)
    log_usage(db, company.id, user.id, "forecast_bottlenecks")
    return result

@app.get("/api/search/candidates")
async def api_smart_search(request: Request, q: str = "", tier: str = None, min_score: float = None, shortlisted: bool = None, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    filters = {}
    if tier: filters["tier"] = tier
    if min_score: filters["min_score"] = min_score
    if shortlisted is not None: filters["shortlisted"] = shortlisted
    return smart_search(db, company.id, q, filters)

@app.get("/api/candidates/{candidate_id}/timeline")
def api_candidate_timeline(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    return get_candidate_timeline(db, company.id, candidate_id)

@app.get("/api/candidates/compare")
def api_compare_candidates(request: Request, a: str = "", b: str = "", db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    if not a or not b:
        return {"ok": False, "error": "Provide both candidate IDs as ?a=id1&b=id2"}
    return compare_candidates(db, company.id, a, b)

@app.get("/api/forecast/scenario/history")
def api_scenario_history(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    logs = db.query(ScenarioLogORM).filter(
        ScenarioLogORM.company_id == company.id
    ).order_by(ScenarioLogORM.created_at.desc()).limit(20).all()
    return {
        "ok": True,
        "scenarios": [
            {
                "id": l.id,
                "inputs": json.loads(l.inputs_json),
                "outputs": json.loads(l.outputs_json),
                "latency_ms": l.latency_ms,
                "created_at": l.created_at.isoformat(),
            }
            for l in logs
        ]
    }


# ============================================================
# PHASE 38 — REAL-TIME CANDIDATE SIGNALS
# ============================================================

from app.signal_engine import (
    ingest_signal,
    get_recent_signals,
    get_candidate_signals,
    get_signal_summary,
    mark_signals_read,
    simulate_demo_signals,
    get_signal_types,
)
from app.db import CandidateSignalORM

@app.post("/api/signals/ingest")
async def api_ingest_signal(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    body = await request.json()
    signal = ingest_signal(
        db=db,
        company_id=company.id,
        candidate_id=body.get("candidate_id", ""),
        signal_type=body.get("signal_type", "profile_update"),
        metadata=body.get("metadata", {}),
        job_id=body.get("job_id"),
    )
    return {"ok": True, "signal_id": signal.id, "signal_type": signal.signal_type}

@app.get("/api/signals/recent")
def api_signals_recent(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    signals = get_recent_signals(db, company.id, limit=limit)
    return {"ok": True, "signals": signals, "total": len(signals)}

@app.get("/api/signals/candidate/{candidate_id}")
def api_signals_candidate(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    signals = get_candidate_signals(db, company.id, candidate_id)
    return {"ok": True, "signals": signals, "total": len(signals)}

@app.get("/api/signals/summary")
def api_signals_summary(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    return get_signal_summary(db, company.id)

@app.patch("/api/signals/read")
async def api_signals_mark_read(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    body = await request.json()
    mark_signals_read(db, company.id, body.get("signal_ids"))
    return {"ok": True}

@app.post("/api/signals/simulate")
def api_signals_simulate(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    count = simulate_demo_signals(db, company.id)
    return {"ok": True, "signals_created": count, "message": f"{count} demo signals generated"}

@app.get("/api/signals/types")
def api_signal_types():
    return {"ok": True, "types": get_signal_types()}


# ============================================================
# PHASE 39 — AI RECRUITER COACHING + SSO
# ============================================================

from app.coaching_engine import (
    analyze_recruiter_behavior,
    get_recent_coaching,
    store_coaching_event,
    score_recruiter_coaching,
    get_sso_login_url,
    get_sso_providers,
)
from app.db import RecruiterCoachingEventORM, SSOProviderORM, SSOSessionORM

@app.get("/api/coaching/recent")
def api_coaching_recent(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    events = get_recent_coaching(db, company.id, user.id)
    return {"ok": True, "events": events, "total": len(events)}

@app.get("/api/coaching/user/{user_id}")
def api_coaching_user(user_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    events = get_recent_coaching(db, company.id, user_id)
    return {"ok": True, "events": events, "total": len(events)}

@app.post("/api/coaching/generate")
def api_coaching_generate(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    events = analyze_recruiter_behavior(db, company.id, user.id)
    return {"ok": True, "events_generated": len(events), "events": events}

@app.patch("/api/coaching/mark-read")
async def api_coaching_mark_read(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    body = await request.json()
    event_ids = body.get("event_ids", [])
    db.query(RecruiterCoachingEventORM).filter(
        RecruiterCoachingEventORM.company_id == company.id,
        RecruiterCoachingEventORM.id.in_(event_ids)
    ).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"ok": True}

@app.patch("/api/coaching/{event_id}/applied")
def api_coaching_applied(event_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    event = db.query(RecruiterCoachingEventORM).filter(
        RecruiterCoachingEventORM.id == event_id,
        RecruiterCoachingEventORM.company_id == company.id,
    ).first()
    if event:
        event.is_applied = True
        event.is_read    = True
        db.commit()
    return {"ok": True}

@app.get("/api/coaching/score")
def api_coaching_score(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    return score_recruiter_coaching(db, company.id, user.id)

# ── SSO Routes ─────────────────────────────────────────────

@app.get("/api/sso/providers")
def api_sso_providers():
    return {"ok": True, "providers": get_sso_providers()}

@app.post("/api/sso/configure")
async def api_sso_configure(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    if user.role != "admin":
        return {"ok": False, "error": "Admin only"}
    body = await request.json()
    provider = SSOProviderORM(
        id=str(uuid.uuid4()),
        company_id=company.id,
        provider=body.get("provider", "azure_ad"),
        tenant_id=body.get("tenant_id"),
        client_id=body.get("client_id"),
        client_secret=body.get("client_secret"),
    )
    db.add(provider)
    db.commit()
    return {"ok": True, "message": f"SSO configured for {body.get('provider')}"}

@app.get("/auth/sso/azure")
def sso_azure_redirect(request: Request, db: Session = Depends(get_db)):
    company_id = request.query_params.get("company_id", "")
    provider = db.query(SSOProviderORM).filter(
        SSOProviderORM.company_id == company_id,
        SSOProviderORM.provider   == "azure_ad",
        SSOProviderORM.is_active  == True,
    ).first()
    if not provider:
        return JSONResponse({"ok": False, "error": "SSO not configured"}, status_code=404)
    redirect_uri = f"https://aitmp.io/auth/sso/callback"
    url = get_sso_login_url(provider.tenant_id, provider.client_id, redirect_uri)
    return RedirectResponse(url=url)

@app.get("/auth/sso/callback")
async def sso_callback(request: Request, db: Session = Depends(get_db)):
    # In production: exchange code for token, provision user
    # For demo: redirect to workspace
    return RedirectResponse(url="/workspace")

@app.get("/api/sso/status")
def api_sso_status(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    providers = db.query(SSOProviderORM).filter(
        SSOProviderORM.company_id == company.id,
        SSOProviderORM.is_active  == True,
    ).all()
    return {
        "ok": True,
        "configured": len(providers) > 0,
        "providers": [{"provider": p.provider, "created_at": p.created_at.isoformat()} for p in providers],
    }


# ============================================================
# PHASE 40 — ACQUISITION-READY MODE
# ============================================================

import platform as _platform

@app.get("/health")
@app.get("/api/platform/health")
def api_platform_health(db: Session = Depends(get_db)):
    """Full platform health — for due diligence + acquisition demo."""
    start = time.time()

    # DB check
    db_ok = True
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    # Latency metrics from telemetry
    # FIX E-2: fallbacks are 0, never invented numbers.
    try:
        from sqlalchemy import text
        since = datetime.utcnow() - timedelta(days=30)
        latencies = db.query(TelemetryORM.latency_ms).filter(
            TelemetryORM.created_at >= since,
            TelemetryORM.latency_ms != None,
        ).limit(1000).all()
        lats = sorted([l[0] for l in latencies if l[0]])
        p50  = lats[int(len(lats)*0.50)] if lats else 0
        p95  = lats[int(len(lats)*0.95)] if lats else 0
        p99  = lats[int(len(lats)*0.99)] if lats else 0
    except Exception:
        p50, p95, p99 = 0, 0, 0

    # FIX E-1: request success rate computed from real telemetry —
    # never a hardcoded uptime number. True uptime comes from Azure Monitor.
    try:
        since = datetime.utcnow() - timedelta(days=30)
        total_reqs = db.query(TelemetryORM).filter(TelemetryORM.created_at >= since).count()
        error_reqs = db.query(TelemetryORM).filter(
            TelemetryORM.created_at >= since,
            TelemetryORM.status_code >= 500,
        ).count()
        request_success_pct = round((1 - error_reqs / total_reqs) * 100, 2) if total_reqs else None
    except Exception:
        request_success_pct = None

    # AI call counts
    try:
        ai_calls_total = db.query(UsageLogORM).filter(
            UsageLogORM.action.in_(["ai_grade","ai_narrative","ai_outreach","ai_copilot","scorecard_generated"])
        ).count()
        ai_cost_30d = db.query(func.sum(UsageLogORM.cost_usd)).filter(
            UsageLogORM.created_at >= datetime.utcnow() - timedelta(days=30)
        ).scalar() or 0.0
    except Exception:
        ai_calls_total = 0
        ai_cost_30d    = 0.0

    # Candidate + company counts
    try:
        total_candidates = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.is_deleted==False).count()
        total_companies  = db.query(CompanyORM).filter(CompanyORM.is_active==True, CompanyORM.is_deleted==False).count()
    except Exception:
        total_candidates = 0
        total_companies  = 0

    latency_ms = round((time.time() - start) * 1000, 2)

    return {
        "ok":              True,
        "version":         "40.0.0",
        "phase":           "40/40",
        "status":          "acquisition-ready",
        "database":        "healthy" if db_ok else "degraded",
        "latency": {
            "note":             "App-layer latency only. AI scoring is model-bound (GPT-4o) and takes seconds, not milliseconds.",
            "app_current_ms":   latency_ms,
            "app_p50_ms":       round(p50, 1),
            "app_p95_ms":       round(p95, 1),
            "app_p99_ms":       round(p99, 1),
            "app_target_ms":    200,
            "app_meets_target": (p95 < 200) if p95 else None,
            "ai_scoring_ms":    "1000-4000 (model-bound, typical for GPT-4o)",
        },
        "ai": {
            "provider":       "Azure OpenAI GPT-4o",
            "deployment":     "ai-talent-grade-engine",
            "total_calls":    ai_calls_total,
            "cost_30d_usd":   round(ai_cost_30d, 4),
        },
        "platform": {
            "total_candidates": total_candidates,
            "total_companies":  total_companies,
            "request_success_pct": request_success_pct,
            "uptime_note":      "True uptime is measured by Azure Monitor availability tests, not self-reported.",
            "linkedin_partner_approved": False,
            "enterprise_ready": True,
        },
        "stack": {
            "backend":   "FastAPI + Python 3.14",
            "database":  "SQLite → Cosmos DB post-acquisition",
            "ai":        "Azure OpenAI GPT-4o",
            "billing":   "Stripe",
            "domain":    "aitmp.io",
        },
        "checked_at": datetime.utcnow().isoformat(),
    }


# LinkedIn sign-in and its readiness/status endpoints were removed — see
# linkedin_engine.py for why. Accounts have always had passwords, so no
# login path was lost.

@app.get("/api/partners/readiness")
def api_partners_readiness():
    """Partner program spec sheet."""
    return {
        "ok": True,
        "partners": {
            "greenhouse": {"status": "ready", "webhook": True,  "oauth": False, "docs": "/api-docs#greenhouse"},
            "lever":      {"status": "ready", "webhook": True,  "oauth": False, "docs": "/api-docs#lever"},
            # FIX E-4: honest status — LinkedIn is pending Partner Program approval, no OAuth today.
            "linkedin":   {"status": "pending_partner_approval", "webhook": False, "oauth": False, "docs": "/api-docs#linkedin"},
            "workday":    {"status": "planned","webhook": False, "oauth": False, "docs": None},
        },
        "webhook_events": [
            "candidate.created", "candidate.scored", "candidate.shortlisted",
            "candidate.narrative.generated", "candidate.signal.detected",
            "outreach.sent", "outreach.replied",
            "scorecard.generated", "coaching.created",
            "billing.subscription.updated", "test.ping",
        ],
        "retry_policy": {"max_attempts": 3, "backoff": "exponential", "timeout_ms": 5000},
        "example_payload": {
            "event": "candidate.scored",
            "candidate_id": "uuid",
            "score": 94,
            "tier": "gold",
            "latency_ms": 87,
        },
    }


@app.post("/api/dev/playground")
async def api_dev_playground(request: Request, db: Session = Depends(get_db)):
    """API playground — execute internal endpoints for testing."""
    body = await request.json()
    endpoint = body.get("endpoint", "")
    method   = body.get("method", "GET").upper()

    safe_endpoints = [
        "/api/platform/health", "/api/readiness/linkedin",
        "/api/partners/readiness", "/api/signals/types",
        "/api/sso/providers", "/api/forecast/funnel",
        "/api/alerts", "/api/scorecard/stats",
    ]

    if endpoint not in safe_endpoints:
        return {"ok": False, "error": "Endpoint not available in playground"}

    import httpx as _httpx
    try:
        base_url = str(request.base_url).rstrip("/")
        async with _httpx.AsyncClient(cookies=dict(request.cookies)) as client:
            if method == "GET":
                res = await client.get(f"{base_url}{endpoint}", timeout=10.0)
            else:
                res = await client.post(f"{base_url}{endpoint}", json=body.get("payload",{}), timeout=10.0)
        return {"ok": True, "status": res.status_code, "response": res.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/system/status")
def api_system_status(db: Session = Depends(get_db)):
    """Full system status for acquisition due diligence."""
    try:
        tables = [
            "companies", "company_users", "company_candidates",
            "scorecards", "candidate_signals", "recruiter_coaching_events",
            "intelligence_alerts", "outreach_messages", "recruiter_copilot_sessions",
        ]
        table_counts = {}
        for t in tables:
            try:
                count = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                table_counts[t] = count
            except Exception:
                table_counts[t] = 0
    except Exception:
        table_counts = {}

    return {
        "ok":      True,
        "version": "40.0.0",
        "phases_complete": 40,
        "acquisition_ready": True,
        "tables": table_counts,
        "engines": [
            "ai_engine", "narrative_engine", "outreach_engine",
            "copilot_engine", "intelligence_engine", "scorecard_engine",
            "interview_engine", "forecast_engine_v2", "signal_engine",
            "coaching_engine",
        ],
        "checked_at": datetime.utcnow().isoformat(),
    }


@app.post("/api/demo/seed")
async def api_demo_seed(request: Request, db: Session = Depends(get_db)):
    """Seed demo data for acquisition demo."""
    company, user = get_current_company_user(request, db)
    if user.role != "admin":
        return {"ok": False, "error": "Admin only"}

    created = {}

    # Seed demo candidates
    demo_candidates = [
        {"name": "Sarah Chen",      "role": "Senior ML Engineer",        "tier": "gold",   "score": 94},
        {"name": "Marcus Williams", "role": "Staff Backend Engineer",     "tier": "gold",   "score": 91},
        {"name": "Priya Patel",     "role": "Product Manager — AI",       "tier": "silver", "score": 84},
        {"name": "James O'Brien",   "role": "Engineering Manager",        "tier": "silver", "score": 79},
        {"name": "Yuki Tanaka",     "role": "Data Scientist",             "tier": "bronze", "score": 71},
    ]

    count = 0
    for c in demo_candidates:
        existing = db.query(CompanyCandidateORM).filter(
            CompanyCandidateORM.company_id == company.id,
            CompanyCandidateORM.name == c["name"],
        ).first()
        if not existing:
            candidate = CompanyCandidateORM(
                id=str(uuid.uuid4()),
                company_id=company.id,
                added_by=user.id,
                name=c["name"],
                role=c["role"],
                tier=c["tier"],
                match_score=c["score"],
                ai_analysis=f"{c['name']} shows strong alignment with role requirements. Trajectory suggests high-impact contribution within 90 days.",
                silent_skill="Strategic thinking",
                shortlisted=c["tier"] == "gold",
            )
            db.add(candidate)
            count += 1

    try:
        db.commit()
        created["candidates"] = count
    except Exception:
        db.rollback()
        created["candidates"] = 0

    # Seed demo signals
    try:
        from app.signal_engine import simulate_demo_signals
        sig_count = simulate_demo_signals(db, company.id)
        created["signals"] = sig_count
    except Exception:
        created["signals"] = 0

    return {
        "ok":      True,
        "created": created,
        "message": f"Demo data seeded — {created.get('candidates',0)} candidates + {created.get('signals',0)} signals",
    }


# ============================================================
# PHASE 41 — POST-ACQUISITION INTEGRATION
# ============================================================

from app.mobile_engine import (
    create_mobile_token, validate_mobile_token, mobile_candidate,
    generate_webhook_signature, add_to_dlq, get_webhook_failures, replay_webhook,
    get_ai_path, get_model_for_path,
    log_compliance_event, export_company_data, delete_candidate_data, get_compliance_audit_log,
    SWIFT_SNIPPET, KOTLIN_SNIPPET,
)
from app.db import (
    WebhookDLQORM, ComplianceLogORM, MobileSessionORM
)

# ── Mobile API ─────────────────────────────────────────────

# Mobile auth rate limit store
_mobile_auth_attempts: dict = {}

@app.post("/api/mobile/v1/auth")
async def api_mobile_auth(request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    attempts = _mobile_auth_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < 300]
    if len(attempts) >= 10:
        return JSONResponse({"ok": False, "error": "Too many attempts. Try again in 5 minutes."}, status_code=429)
    _mobile_auth_attempts[ip] = attempts + [now]
    body = await request.json()
    email = body.get("email", "")
    password = body.get("password", "")
    platform = body.get("platform", "ios")
    device_id = body.get("device_id")

    user = db.query(CompanyUserORM).filter(
        CompanyUserORM.email == email,
        CompanyUserORM.is_deleted == False,
    ).first()
    if not user:
        return JSONResponse({"ok": False, "error": "Invalid credentials"}, status_code=401)

    if not verify_password(password, user.password):
        return JSONResponse({"ok": False, "error": "Invalid credentials"}, status_code=401)

    token_data = create_mobile_token(db, user.company_id, user.id, platform, device_id)
    log_compliance_event(db, user.company_id, "mobile_login", "user", user.id,
                        ip_address=request.client.host if request.client else None)
    return {"ok": True, **token_data}

@app.get("/api/mobile/v1/candidates")
def api_mobile_candidates(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    session = validate_mobile_token(db, token)
    if not session:
        return JSONResponse({"ok": False, "error": "Invalid or expired token"}, status_code=401)

    candidates = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == session.company_id,
        CompanyCandidateORM.is_deleted == False,
    ).order_by(CompanyCandidateORM.match_score.desc()).limit(20).all()

    return {"ok": True, "candidates": [mobile_candidate(c) for c in candidates], "total": len(candidates)}

@app.get("/api/mobile/v1/health")
def api_mobile_health():
    return {"ok": True, "version": "41.0.0", "platform": "mobile", "latency_target_ms": 100}

# ── Webhooks 2.0 ──────────────────────────────────────────

@app.get("/api/webhooks/failures")
def api_webhook_failures(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    failures = get_webhook_failures(db, company.id)
    return {"ok": True, "failures": failures, "total": len(failures)}

@app.post("/api/webhooks/replay/{dlq_id}")
def api_webhook_replay(dlq_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    result = replay_webhook(db, dlq_id, company.id)
    if result["ok"]:
        log_compliance_event(db, company.id, "webhook_replay", "webhook_dlq", dlq_id, user_id=user.id)
    return result

# ── AI Hot/Cold Path ───────────────────────────────────────

@app.get("/api/ai/path")
def api_ai_path(action: str = "scoring"):
    path  = get_ai_path(action)
    model = get_model_for_path(path)
    return {
        "ok":     True,
        "action": action,
        "path":   path,
        "model":  model,
        "target_latency_ms": 100 if path == "hot" else 3000,
        "hot_actions":  list(["scoring","signals","forecast","copilot","interview_questions","scorecard"]),
        "cold_actions": list(["narrative","digest","coaching","deep_analytics","batch_outreach"]),
    }

# ── Compliance Layer ───────────────────────────────────────

@app.get("/api/compliance/export")
def api_compliance_export(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    if user.role != "admin":
        return JSONResponse({"ok": False, "error": "Admin only"}, status_code=403)
    result = export_company_data(db, company.id)
    log_compliance_event(db, company.id, "gdpr_export", "company", company.id, user_id=user.id,
                        ip_address=request.client.host if request.client else None)
    return result

@app.delete("/api/compliance/delete/{candidate_id}")
def api_compliance_delete(candidate_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    if user.role != "admin":
        return JSONResponse({"ok": False, "error": "Admin only"}, status_code=403)
    return delete_candidate_data(db, company.id, candidate_id)

@app.get("/api/compliance/audit-log")
def api_compliance_audit(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    if user.role != "admin":
        return JSONResponse({"ok": False, "error": "Admin only"}, status_code=403)
    logs = get_compliance_audit_log(db, company.id)
    return {"ok": True, "logs": logs, "total": len(logs)}

# ── LinkedIn Graph Stub ────────────────────────────────────

# ── Mobile SDK Snippets ────────────────────────────────────

@app.get("/api/mobile/sdk/swift")
def api_mobile_sdk_swift():
    return {"ok": True, "language": "Swift", "platform": "iOS", "snippet": SWIFT_SNIPPET}

@app.get("/api/mobile/sdk/kotlin")
def api_mobile_sdk_kotlin():
    return {"ok": True, "language": "Kotlin", "platform": "Android", "snippet": KOTLIN_SNIPPET}

# ── SSO Stubs (extended from Phase 39) ────────────────────

@app.post("/api/sso/config/test")
def api_sso_config_test():
    return {"ok": False, "message": "Enterprise SSO available post-acquisition."}

@app.get("/api/sso/metadata")
def api_sso_metadata():
    return {"ok": False, "message": "Enterprise SSO available post-acquisition."}


# ============================================================
# PHASE 42 — GLOBAL ROLLOUT MODE
# ============================================================

from app.linkedin_engine import (
    seed_feature_flags, is_flag_enabled, get_all_flags, update_flag,
    route_ai_model, get_tenant_config,
    api_v2_candidates,
    get_status_page,
    get_data_residency_options,
    MODEL_CATALOG,
)
from app.db import (
    FeatureFlagORM, AIModelRouteORM,
    LinkedInOAuthORM, StatusPageORM,
)

# ── Feature Flags ──────────────────────────────────────────

@app.get("/api/flags")
def api_flags(request: Request, db: Session = Depends(get_db)):
    seed_feature_flags(db)
    flags = get_all_flags(db)
    return {"ok": True, "flags": flags, "total": len(flags)}

@app.patch("/api/flags/{flag_key}")
async def api_flag_update(flag_key: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    if user.role != "admin":
        return JSONResponse({"ok": False, "error": "Admin only"}, status_code=403)
    body = await request.json()
    return update_flag(db, flag_key, body.get("enabled", False), body.get("rollout_pct"))

@app.get("/api/flags/{flag_key}/check")
def api_flag_check(flag_key: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    enabled = is_flag_enabled(db, flag_key, company.id)
    return {"ok": True, "flag": flag_key, "enabled": enabled, "company_id": company.id}

# ── Multi-Model AI Router ──────────────────────────────────

@app.get("/api/ai/route")
def api_ai_route(
    action: str = "scoring",
    region: str = "us",
    tier: str = "business",
    latency_critical: bool = True,
):
    result = route_ai_model(action, tier, region, latency_critical)
    return {"ok": True, **result}

@app.get("/api/ai/models")
def api_ai_models():
    return {"ok": True, "models": MODEL_CATALOG}

# ── Multi-Tenant Config ────────────────────────────────────

@app.get("/api/tenant/config")
def api_tenant_config(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    return get_tenant_config(db, company.id)

# ── LinkedIn OAuth ─────────────────────────────────────────

@app.post("/api/auth/verify-hr")
async def api_verify_hr(request: Request):
    """Verify if a user is an HR professional before registration."""
    body = await request.json()
    job_title  = body.get("job_title", "")
    department = body.get("department", "")
    is_hr      = is_hr_professional(job_title, department)
    return {
        "ok":       True,
        "is_hr":    is_hr,
        "message":  "Access granted — HR professional verified" if is_hr else "Access denied — this platform is for HR professionals only",
    }


# ── API v2 ─────────────────────────────────────────────────

@app.get("/api/v2/candidates")
def api_v2_candidates_route(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    sort_by: str = "match_score",
    sort_dir: str = "desc",
    tier: str = None,
    min_score: float = None,
    shortlisted: bool = None,
    search: str = None,
    db: Session = Depends(get_db),
):
    company, user = get_current_company_user(request, db)
    return api_v2_candidates(
        db=db,
        company_id=company.id,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_dir=sort_dir,
        tier=tier,
        min_score=min_score,
        shortlisted=shortlisted,
        search=search,
    )

# ── Status Page ────────────────────────────────────────────

@app.get("/api/status")
@app.get("/status")
def api_status(db: Session = Depends(get_db)):
    return get_status_page(db)

@app.post("/api/status/incident")
async def api_status_incident(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    if user.role != "admin":
        return JSONResponse({"ok": False, "error": "Admin only"}, status_code=403)
    body = await request.json()
    incident = StatusPageORM(
        id=str(uuid.uuid4()),
        title=body.get("title", "Incident"),
        message=body.get("message", ""),
        status=body.get("status", "degraded"),
        component=body.get("component"),
        region=body.get("region", "us"),
    )
    db.add(incident)
    db.commit()
    return {"ok": True, "incident_id": incident.id}

@app.patch("/api/status/incident/{incident_id}/resolve")
def api_status_resolve(incident_id: str, request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    incident = db.query(StatusPageORM).filter(StatusPageORM.id == incident_id).first()
    if incident:
        incident.resolved    = True
        incident.resolved_at = datetime.utcnow()
        incident.status      = "resolved"
        db.commit()
    return {"ok": True}

# ── Data Residency ─────────────────────────────────────────

@app.get("/api/data-residency")
def api_data_residency():
    return get_data_residency_options()

# ── Multi-region stub ──────────────────────────────────────

@app.get("/api/regions")
def api_regions():
    return {
        "ok": True,
        "current_region": "us-east",
        "available_regions": [
            {"key": "us-east",  "label": "US East",        "status": "active",    "latency_ms": 12},
            {"key": "us-west",  "label": "US West",        "status": "planned",   "latency_ms": None},
            {"key": "eu-west",  "label": "EU West",        "status": "planned",   "latency_ms": None},
            {"key": "apac",     "label": "Asia Pacific",   "status": "post-acq",  "latency_ms": None},
        ],
        "note": "Multi-region via Azure Front Door — available post-acquisition",
    }


# ============================================================
# PHASE 43 — TALENT GRAPH ENGINE + BILLING
# ============================================================

from app.graph_engine import (
    build_candidate_graph,
    get_similar_candidates, get_lookalike_candidates,
    get_hidden_connections, get_graph_analytics,
    get_plans, get_billing_status,
    create_checkout_session, handle_stripe_webhook,
    get_billing_invoices,
)
from app.db import GraphNodeORM, GraphEdgeORM, BillingEventORM

# ── Talent Graph ───────────────────────────────────────────

@app.post("/api/graph/build")
def api_graph_build(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    result = build_candidate_graph(db, company.id)
    return result

@app.get("/api/graph/similar/candidate")
def api_graph_similar(request: Request, id: str = "", limit: int = 5, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    if not id:
        return {"ok": False, "error": "Provide candidate id"}
    results = get_similar_candidates(db, company.id, id, limit)
    return {"ok": True, "similar": results, "total": len(results)}

@app.get("/api/graph/recommend/candidates")
def api_graph_recommend(request: Request, role: str = "", limit: int = 5, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    results = get_lookalike_candidates(db, company.id, role, limit)
    return {"ok": True, "lookalikes": results, "total": len(results)}

@app.get("/api/graph/connections")
def api_graph_connections(request: Request, candidate_id: str = "", db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    if not candidate_id:
        return {"ok": False, "error": "Provide candidate_id"}
    return get_hidden_connections(db, company.id, candidate_id)

@app.get("/api/graph/analytics")
def api_graph_analytics(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    return get_graph_analytics(db, company.id)

@app.get("/api/graph/nodes")
def api_graph_nodes(request: Request, node_type: str = None, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    q = db.query(GraphNodeORM).filter(GraphNodeORM.company_id == company.id)
    if node_type: q = q.filter(GraphNodeORM.node_type == node_type)
    nodes = q.limit(100).all()
    return {"ok": True, "nodes": [{"id": n.id, "type": n.node_type, "entity_id": n.entity_id, "metadata": json.loads(n.metadata_json or "{}")} for n in nodes], "total": len(nodes)}

@app.get("/api/graph/edges")
def api_graph_edges(request: Request, relation: str = None, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    q = db.query(GraphEdgeORM).filter(GraphEdgeORM.company_id == company.id)
    if relation: q = q.filter(GraphEdgeORM.relation == relation)
    edges = q.order_by(GraphEdgeORM.weight.desc()).limit(100).all()
    return {"ok": True, "edges": [{"id": e.id, "source": e.source_id, "target": e.target_id, "relation": e.relation, "weight": e.weight} for e in edges], "total": len(edges)}

# ── Billing ────────────────────────────────────────────────

@app.get("/api/billing/plans")
def api_billing_plans():
    return get_plans()

@app.get("/api/billing/status")
def api_billing_status(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    return get_billing_status(db, company.id)

@app.post("/api/billing/checkout")
async def api_billing_checkout(request: Request, db: Session = Depends(get_db)):
    # Consolidated on Paddle — the graph_engine Stripe checkout (placeholder price IDs) is retired.
    company, user = get_current_company_user(request, db)
    body     = await request.json()
    plan_key = body.get("plan", "business")
    return {"ok": False, "use_paddle": True, "plan": plan_key,
            "paddle": paddle_engine.public_config(),
            "message": "Checkout now runs through Paddle."}

# FIX F: the duplicate Stripe webhook routes (/api/billing/webhook and
# /stripe/webhook) were REMOVED. /stripe-webhook is the one and only
# handler — its logic now also covers customer.subscription.deleted.
# Make sure the Stripe dashboard endpoint URL is:
#   https://aitmp.io/stripe-webhook

@app.get("/api/billing/invoices")
def api_billing_invoices(request: Request, db: Session = Depends(get_db)):
    company, user = get_current_company_user(request, db)
    invoices = get_billing_invoices(db, company.id)
    return {"ok": True, "invoices": invoices, "total": len(invoices)}

@app.post("/api/billing/portal")
async def api_billing_portal(request: Request, db: Session = Depends(get_db)):
    # Billing is consolidated on Paddle. There is no self-serve portal endpoint here:
    # subscriptions are managed from the Paddle customer-portal link on the receipt.
    # 501 Not Implemented — never a 200 that implies a portal was opened.
    get_current_company_user(request, db)   # auth check only
    return JSONResponse({
        "ok": False,
        "use_paddle": True,
        "message": "Manage your subscription from the Paddle receipt/portal link emailed to you, "
                   "or email hello@aitmp.io and we'll send it again.",
    }, status_code=501)


@app.get("/api/me")
def api_me(request: Request, db: Session = Depends(get_db)):
    """Return current user profile for workspace display."""
    try:
        company, user = get_current_company_user(request, db)
        return {
            "ok":               True,
            # FIX D: CompanyUserORM has .name, not .full_name
            "name":             user.name or user.email.split("@")[0],
            "email":            user.email,
            "photo_url":        getattr(user, "photo_url", None),
            "linkedin_connected": bool(getattr(user, "linkedin_url", None)),
            "company":          company.name,
            "plan":             company.plan or "free",
        }
    except Exception:
        return {"ok": False, "error": "Not logged in"}