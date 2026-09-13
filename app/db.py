from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime,
    Boolean, Float, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import datetime
import enum
import os

# DB location is configurable so production can use persistent storage that SURVIVES deploys.
# Azure App Service: /home is persistent and lives OUTSIDE wwwroot (which `--clean` deploys wipe),
# so set DATABASE_PATH=/home/data/elinor.db there. Locally it defaults to ./elinor.db.
_DB_PATH = os.getenv("DATABASE_PATH", "").strip()
if _DB_PATH:
    _db_dir = os.path.dirname(_DB_PATH)
    if _db_dir:
        os.makedirs(_db_dir, exist_ok=True)  # SQLite won't create the parent dir itself
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{_DB_PATH}"
else:
    SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./elinor.db")

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ============================================================
# EXISTING TABLES (unchanged)
# ============================================================

class IdeaORM(Base):
    __tablename__ = "ideas"
    id          = Column(Integer, primary_key=True, index=True)
    title       = Column(String(120), nullable=False)
    description = Column(Text, nullable=False)
    author      = Column(String(120))
    timestamp   = Column(DateTime, default=datetime.utcnow, nullable=False)

class ProjectORM(Base):
    __tablename__ = "projects"
    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(120), nullable=False)
    status     = Column(String(50), nullable=False)
    owner      = Column(String(120))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class AnswerORM(Base):
    __tablename__ = "answers"
    id            = Column(Integer, primary_key=True, index=True)
    question_text = Column(Text, nullable=False)
    user          = Column(String(120))
    timestamp     = Column(DateTime, default=datetime.utcnow, nullable=False)
    answer        = Column(Text, nullable=False)

class ConversationORM(Base):
    __tablename__ = "conversations"
    id              = Column(Integer, primary_key=True, index=True)
    user_email      = Column(String(200), nullable=False)
    role_title      = Column(String(200), nullable=False)
    human_story     = Column(Text)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)
    search_strategy = Column(Text)
    candidates      = relationship("CandidateMatchORM", back_populates="conversation")

class CandidateMatchORM(Base):
    __tablename__ = "candidate_matches"
    id                 = Column(Integer, primary_key=True, index=True)
    search_id          = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    name               = Column(String(200), nullable=False)
    match_score        = Column(Float, nullable=False)
    ai_analysis        = Column(Text, nullable=False)
    linkedin_url       = Column(String(500))
    synthesis_label    = Column(String(200))
    silent_skill       = Column(String(200))
    experience_summary = Column(Text)
    trajectory_match   = Column(String(200))
    created_at         = Column(DateTime, default=datetime.utcnow, nullable=False)
    conversation       = relationship("ConversationORM", back_populates="candidates")

# ============================================================
# PHASE 22 — COMPANY ACCOUNTS
# ============================================================

class CompanyORM(Base):
    __tablename__ = "companies"
    id                 = Column(String(36), primary_key=True, index=True)
    name               = Column(String(120), nullable=False)
    domain             = Column(String(120), unique=True, nullable=False, index=True)
    plan               = Column(String(50), default="free", nullable=False)
    seat_count         = Column(Integer, default=1)
    seat_limit         = Column(Integer, default=1)
    api_key            = Column(String(64), unique=True, nullable=False)
    stripe_customer_id = Column(String(200))
    trial_ends_at        = Column(DateTime, nullable=True)   # set when a card-required trial starts
    trial_reminder_sent  = Column(Boolean, default=False)    # day-6 reminder idempotency guard
    is_active          = Column(Boolean, default=True)
    is_deleted         = Column(Boolean, default=False, index=True)
    deleted_at         = Column(DateTime, nullable=True)
    updated_by         = Column(String(36), nullable=True)
    created_at         = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at         = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    users               = relationship("CompanyUserORM",        back_populates="company", cascade="all, delete-orphan")
    invites             = relationship("TeamInviteORM",          back_populates="company", cascade="all, delete-orphan")
    subscriptions       = relationship("SubscriptionORM",        back_populates="company", passive_deletes=True)
    invoices            = relationship("InvoiceORM",             back_populates="company", passive_deletes=True)
    roles               = relationship("CompanyRoleORM",         back_populates="company", cascade="all, delete-orphan")
    candidates          = relationship("CompanyCandidateORM",    back_populates="company", cascade="all, delete-orphan")
    usage_logs          = relationship("UsageLogORM",            back_populates="company", cascade="all, delete-orphan")
    feedback_events     = relationship("FeedbackEventORM",       back_populates="company", cascade="all, delete-orphan")
    insight_snapshots   = relationship("InsightSnapshotORM",     back_populates="company", cascade="all, delete-orphan")
    data_fusions        = relationship("DataFusionORM",          back_populates="company", cascade="all, delete-orphan")
    cost_optimizer      = relationship("CostOptimizerORM",       back_populates="company", cascade="all, delete-orphan")
    recruiter_analytics = relationship("RecruiterAnalyticsORM",  back_populates="company", cascade="all, delete-orphan")
    # Phase 31
    api_keys            = relationship("APIKeyORM",              back_populates="company", cascade="all, delete-orphan")
    webhooks            = relationship("WebhookORM",             back_populates="company", cascade="all, delete-orphan")
    # Phase 32
    partner_sync_logs   = relationship("PartnerSyncLogORM",      back_populates="company", cascade="all, delete-orphan")
    job_descriptions    = relationship("JobDescriptionORM",      back_populates="company", cascade="all, delete-orphan")
    # Phase 33
    recruiter_projects  = relationship("RecruiterProjectORM",    back_populates="company", cascade="all, delete-orphan")
    outreach_messages   = relationship("OutreachORM",            back_populates="company", cascade="all, delete-orphan")
    copilot_sessions    = relationship("RecruiterCopilotORM",    back_populates="company", cascade="all, delete-orphan")

class CompanyUserORM(Base):
    __tablename__ = "company_users"
    id         = Column(String(36), primary_key=True, index=True)
    email      = Column(String(200), nullable=False, index=True)
    name       = Column(String(120), nullable=False)
    password   = Column(String(200), nullable=False)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    role       = Column(String(20), default="recruiter", nullable=False, index=True)
    is_active  = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False, nullable=False)  # set true after clicking the verify link
    linkedin_url   = Column(String(300), nullable=True)  # stored for future LinkedIn Partner HR verification
    job_title      = Column(String(120), nullable=True)  # HR-title check at register
    photo      = Column(String(500))
    last_login = Column(DateTime)
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True)
    updated_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    __table_args__ = (UniqueConstraint("email", "company_id", name="uq_user_email_company"),)
    company = relationship("CompanyORM", back_populates="users")

class EmailTokenORM(Base):
    """One-time tokens for email verification and password reset (new table — auto-created)."""
    __tablename__ = "email_tokens"
    id         = Column(String(36), primary_key=True, index=True)
    token      = Column(String(64), nullable=False, unique=True, index=True)
    email      = Column(String(200), nullable=False, index=True)
    user_id    = Column(String(36), nullable=True, index=True)
    purpose    = Column(String(20), nullable=False)   # "verify" | "reset"
    expires_at = Column(DateTime, nullable=False)
    used_at    = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

class EmailSubscriberORM(Base):
    """Newsletter / 'notify me' captures from the landing page (new table — auto-created)."""
    __tablename__ = "email_subscribers"
    id         = Column(String(36), primary_key=True, index=True)
    email      = Column(String(200), nullable=False, index=True)
    source     = Column(String(50), default="landing")   # "newsletter" | "mobile_app" | ...
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

class UserORM(Base):
    __tablename__ = "users"
    id              = Column(Integer, primary_key=True, index=True)
    email           = Column(String(200), unique=True, nullable=False)
    domain          = Column(String(200), nullable=False)
    is_validated    = Column(Boolean, default=False)
    membership_tier = Column(String(50), default="free")
    session_token   = Column(String(200), unique=True)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login      = Column(DateTime)
    company_id      = Column(String(36), ForeignKey("companies.id"), nullable=True)

class TeamInviteORM(Base):
    __tablename__ = "team_invites"
    id         = Column(String(36), primary_key=True, index=True)
    email      = Column(String(200), nullable=False, index=True)
    role       = Column(String(20), default="recruiter", nullable=False)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    invited_by = Column(String(36), nullable=False)
    status     = Column(String(20), default="pending", nullable=False, index=True)
    token      = Column(String(100), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_deleted = Column(Boolean, default=False)
    company    = relationship("CompanyORM", back_populates="invites")

class SubscriptionORM(Base):
    __tablename__ = "subscriptions"
    id                     = Column(String(36), primary_key=True, index=True)
    company_id             = Column(String(36), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True)
    plan                   = Column(String(50), nullable=False)
    status                 = Column(String(50), default="trialing", nullable=False, index=True)
    billing_cycle          = Column(String(20), default="monthly", nullable=False)
    price                  = Column(Float, nullable=False)
    stripe_subscription_id = Column(String(200))
    current_period_start   = Column(DateTime, nullable=False)
    current_period_end     = Column(DateTime, nullable=False)
    cancel_at_period_end   = Column(Boolean, default=False)
    created_at             = Column(DateTime, default=datetime.utcnow, nullable=False)
    company                = relationship("CompanyORM", back_populates="subscriptions")

class InvoiceORM(Base):
    __tablename__ = "invoices"
    id                = Column(String(36), primary_key=True, index=True)
    company_id        = Column(String(36), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True)
    amount            = Column(Float, nullable=False)
    currency          = Column(String(10), default="usd")
    status            = Column(String(20), nullable=False, index=True)
    description       = Column(String(500))
    stripe_invoice_id = Column(String(200))
    pdf_url           = Column(String(500))
    issued_at         = Column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at           = Column(DateTime)
    company           = relationship("CompanyORM", back_populates="invoices")

class CompanyRoleORM(Base):
    __tablename__ = "company_roles"
    id          = Column(String(36), primary_key=True, index=True)
    company_id  = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    created_by  = Column(String(36), nullable=False)
    title       = Column(String(200), nullable=False)
    description = Column(Text)
    location    = Column(String(200))
    skills      = Column(Text)
    boolean     = Column(Text)
    is_active   = Column(Boolean, default=True)
    # Archiving frees a plan's active-role slot without deleting any data.
    is_archived = Column(Boolean, default=False, index=True)
    archived_at = Column(DateTime, nullable=True)
    is_deleted  = Column(Boolean, default=False, index=True)
    deleted_at  = Column(DateTime, nullable=True)
    updated_by  = Column(String(36), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    company          = relationship("CompanyORM", back_populates="roles")
    candidates       = relationship("CompanyCandidateORM", back_populates="job")
    forecasts        = relationship("ForecastORM", backref="job")
    job_descriptions = relationship("JobDescriptionORM", back_populates="job", cascade="all, delete-orphan")
    # Phase 33
    recruiter_projects = relationship("RecruiterProjectORM", back_populates="role", cascade="all, delete-orphan")

class CompanyCandidateORM(Base):
    __tablename__ = "company_candidates"
    id                   = Column(String(36), primary_key=True, index=True)
    company_id           = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    job_id               = Column(String(36), ForeignKey("company_roles.id"), nullable=True, index=True)
    added_by             = Column(String(36), nullable=False)
    name                 = Column(String(200), nullable=False)
    role                 = Column(String(200))
    tier                 = Column(String(20), nullable=False, index=True)
    match_score          = Column(Float, nullable=False)
    adaptability         = Column(Float)
    focus_penalty        = Column(Float)
    ai_analysis          = Column(Text)
    silent_skill         = Column(String(200))
    linkedin_url         = Column(String(500))
    photo                = Column(String(500))
    notes                = Column(Text, default="")
    shortlisted          = Column(Boolean, default=False, index=True)
    is_deleted           = Column(Boolean, default=False, index=True)
    deleted_at           = Column(DateTime, nullable=True)
    created_at           = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    # Phase 32
    partner_source       = Column(String(50), nullable=True)
    partner_candidate_id = Column(String(200), nullable=True)
    company      = relationship("CompanyORM", back_populates="candidates")
    job          = relationship("CompanyRoleORM", back_populates="candidates")
    data_fusions = relationship("DataFusionORM", back_populates="candidate", foreign_keys="DataFusionORM.candidate_id")
    # Phase 33
    outreach_messages  = relationship("OutreachORM", back_populates="candidate", cascade="all, delete-orphan")
    project_candidates = relationship("ProjectCandidateORM", back_populates="candidate", cascade="all, delete-orphan")

class UsageLogORM(Base):
    __tablename__ = "usage_logs"
    id         = Column(Integer, primary_key=True, index=True)
    company_id = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    user_id    = Column(String(36), nullable=False, index=True)
    action     = Column(String(100), nullable=False, index=True)
    details    = Column(Text)
    latency_ms = Column(Float)
    cost_usd   = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    company    = relationship("CompanyORM", back_populates="usage_logs")

# ============================================================
# PHASE 23 — INTELLIGENCE LAYER
# ============================================================

class FeedbackEventORM(Base):
    __tablename__ = "feedback_events"
    id             = Column(String(36), primary_key=True, index=True)
    company_id     = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id        = Column(String(36), nullable=False, index=True)
    action         = Column(String(50), nullable=False, index=True)
    signal         = Column(String(20), nullable=False, index=True)
    candidate_id   = Column(String(36), ForeignKey("company_candidates.id"), nullable=True, index=True)
    candidate_name = Column(String(200), nullable=True)
    job_id         = Column(String(36), ForeignKey("company_roles.id"), nullable=True, index=True)
    job_title      = Column(String(200), nullable=True)
    tier           = Column(String(20), nullable=True, index=True)
    match_score    = Column(Float, nullable=True)
    anonymized     = Column(Boolean, default=True)
    is_deleted     = Column(Boolean, default=False, index=True)
    deleted_at     = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    company        = relationship("CompanyORM", back_populates="feedback_events")
    __table_args__ = (
        Index("idx_feedback_company_action", "company_id", "action"),
        Index("idx_feedback_company_signal", "company_id", "signal"),
    )

class FeedbackAggregateORM(Base):
    __tablename__ = "feedback_aggregates"
    id                    = Column(String(36), primary_key=True, index=True)
    company_id            = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    week_start            = Column(DateTime, nullable=False, index=True)
    week_end              = Column(DateTime, nullable=False)
    total_events          = Column(Integer, default=0)
    shortlists            = Column(Integer, default=0)
    skips                 = Column(Integer, default=0)
    hires                 = Column(Integer, default=0)
    views                 = Column(Integer, default=0)
    gold_shortlists       = Column(Integer, default=0)
    silver_shortlists     = Column(Integer, default=0)
    bronze_shortlists     = Column(Integer, default=0)
    avg_shortlisted_score = Column(Float, nullable=True)
    avg_skipped_score     = Column(Float, nullable=True)
    avg_time_to_hire_days = Column(Float, nullable=True)
    is_deleted            = Column(Boolean, default=False, index=True)
    deleted_at            = Column(DateTime, nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow, nullable=False)

class ModelVersionORM(Base):
    __tablename__ = "model_versions"
    id            = Column(String(36), primary_key=True, index=True)
    version       = Column(String(20), nullable=False, unique=True, index=True)
    status        = Column(String(20), default="training", index=True)
    accuracy      = Column(Float, nullable=True)
    precision     = Column(Float, nullable=True)
    recall        = Column(Float, nullable=True)
    cost_per_call = Column(Float, nullable=True)
    training_size = Column(Integer, nullable=True)
    azure_ml_run  = Column(String(200), nullable=True)
    deployed_at   = Column(DateTime, nullable=True)
    notes         = Column(Text, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

class InsightSnapshotORM(Base):
    __tablename__ = "insight_snapshots"
    id                    = Column(String(36), primary_key=True, index=True)
    company_id            = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_date         = Column(DateTime, nullable=False, index=True)
    avg_adaptability      = Column(Float, nullable=True)
    avg_match_score       = Column(Float, nullable=True)
    avg_focus_penalty     = Column(Float, nullable=True)
    avg_time_to_hire_days = Column(Float, nullable=True)
    gold_pct              = Column(Float, nullable=True)
    silver_pct            = Column(Float, nullable=True)
    bronze_pct            = Column(Float, nullable=True)
    shortlist_rate        = Column(Float, nullable=True)
    hire_rate             = Column(Float, nullable=True)
    skip_rate             = Column(Float, nullable=True)
    total_searches        = Column(Integer, default=0)
    total_candidates      = Column(Integer, default=0)
    total_hires           = Column(Integer, default=0)
    is_deleted            = Column(Boolean, default=False, index=True)
    deleted_at            = Column(DateTime, nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow, nullable=False)
    company               = relationship("CompanyORM", back_populates="insight_snapshots")
    __table_args__        = (Index("idx_insight_company_date", "company_id", "snapshot_date"),)

class AINarrativeORM(Base):
    __tablename__ = "ai_narratives"
    id                      = Column(String(36), primary_key=True, index=True)
    candidate_id            = Column(String(36), ForeignKey("company_candidates.id"), nullable=False, index=True)
    company_id              = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    narrative               = Column(Text, nullable=False)
    model_version           = Column(String(20), default="gpt-4o-mini")
    tokens_used             = Column(Integer, nullable=True)
    latency_ms              = Column(Float, nullable=True)
    tone                    = Column(String(50), nullable=True)
    sentiment               = Column(String(20), nullable=True)
    recommendation_strength = Column(Float, nullable=True)
    created_at              = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    expires_at              = Column(DateTime, nullable=True)
    is_deleted              = Column(Boolean, default=False, index=True)
    deleted_at              = Column(DateTime, nullable=True)

class ForecastORM(Base):
    __tablename__ = "forecasts"
    id                       = Column(String(36), primary_key=True, index=True)
    company_id               = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id                   = Column(String(36), ForeignKey("company_roles.id"), nullable=True, index=True)
    forecast_date            = Column(DateTime, nullable=False, index=True)
    hiring_velocity          = Column(Float, nullable=True)
    conversion_probability   = Column(Float, nullable=True)
    est_time_to_hire_days    = Column(Float, nullable=True)
    est_candidates_needed    = Column(Integer, nullable=True)
    predicted_hire_rate      = Column(Float, nullable=True)
    predicted_time_to_hire   = Column(Float, nullable=True)
    confidence_interval_low  = Column(Float, nullable=True)
    confidence_interval_high = Column(Float, nullable=True)
    confidence_score         = Column(Float, nullable=True)
    model_version            = Column(String(20), nullable=True)
    based_on_events          = Column(Integer, default=0)
    is_deleted               = Column(Boolean, default=False, index=True)
    deleted_at               = Column(DateTime, nullable=True)
    created_at               = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    __table_args__           = (Index("idx_forecast_company_job", "company_id", "job_id"),)

class TelemetryORM(Base):
    __tablename__ = "telemetry"
    id          = Column(Integer, primary_key=True, index=True)
    endpoint    = Column(String(200), nullable=False, index=True)
    method      = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=False, index=True)
    latency_ms  = Column(Float, nullable=False, index=True)
    company_id  = Column(String(36), nullable=True, index=True)
    error       = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

# ============================================================
# PHASE 24 — PREDICTIVE OPTIMIZATION
# ============================================================

class DataFusionORM(Base):
    __tablename__ = "data_fusion"
    id               = Column(String(36), primary_key=True, index=True)
    company_id       = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id     = Column(String(36), ForeignKey("company_candidates.id"), nullable=True, index=True)
    feedback_signal  = Column(String(20), nullable=False, index=True)
    latency_ms       = Column(Float, nullable=True)
    tier             = Column(String(20), nullable=True, index=True)
    match_score      = Column(Float, nullable=True)
    adaptability     = Column(Float, nullable=True)
    focus_penalty    = Column(Float, nullable=True)
    ai_version       = Column(String(20), nullable=True)
    job_title        = Column(String(200), nullable=True)
    recruiter_action = Column(String(50), nullable=True)
    fused_at         = Column(DateTime, nullable=False, index=True)
    is_deleted       = Column(Boolean, default=False, index=True)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    company          = relationship("CompanyORM", back_populates="data_fusions")
    candidate        = relationship("CompanyCandidateORM", foreign_keys=[candidate_id], back_populates="data_fusions")
    __table_args__ = (
        Index("idx_fusion_company_signal", "company_id", "feedback_signal"),
        Index("idx_fusion_company_tier",   "company_id", "tier"),
    )

class CostOptimizerORM(Base):
    __tablename__ = "cost_optimizer"
    id                  = Column(String(36), primary_key=True, index=True)
    company_id          = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    month               = Column(String(7), nullable=False, index=True)
    ai_calls_this_month = Column(Integer, default=0)
    ai_calls_limit      = Column(Integer, default=100)
    ai_calls_remaining  = Column(Integer, default=100)
    avg_latency_ms      = Column(Float, default=0.0)
    p95_latency_ms      = Column(Float, default=0.0)
    p99_latency_ms      = Column(Float, default=0.0)
    total_cost_usd      = Column(Float, default=0.0)
    cost_per_call_avg   = Column(Float, default=0.0)
    budget_limit_usd    = Column(Float, default=10.0)
    budget_alert_sent   = Column(Boolean, default=False)
    is_throttled        = Column(Boolean, default=False)
    throttled_at        = Column(DateTime, nullable=True)
    throttle_reason     = Column(String(200), nullable=True)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at          = Column(DateTime, default=datetime.utcnow, nullable=False)
    company             = relationship("CompanyORM", back_populates="cost_optimizer")
    __table_args__ = (
        UniqueConstraint("company_id", "month", name="uq_cost_company_month"),
        Index("idx_cost_company_month", "company_id", "month"),
    )

class RecruiterAnalyticsORM(Base):
    __tablename__ = "recruiter_analytics"
    id                     = Column(String(36), primary_key=True, index=True)
    company_id             = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id                = Column(String(36), nullable=False, index=True)
    user_name              = Column(String(120), nullable=True)
    period                 = Column(String(7), nullable=False, index=True)
    total_decisions        = Column(Integer, default=0)
    positive_signals       = Column(Integer, default=0)
    negative_signals       = Column(Integer, default=0)
    hire_count             = Column(Integer, default=0)
    shortlist_count        = Column(Integer, default=0)
    skip_count             = Column(Integer, default=0)
    avg_time_to_decision_s = Column(Float, nullable=True)
    decisions_per_day      = Column(Float, nullable=True)
    avg_score_shortlisted  = Column(Float, nullable=True)
    avg_score_skipped      = Column(Float, nullable=True)
    gold_preference_rate   = Column(Float, nullable=True)
    tier_diversity_score   = Column(Float, nullable=True)
    is_deleted             = Column(Boolean, default=False, index=True)
    deleted_at             = Column(DateTime, nullable=True)
    updated_at             = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at             = Column(DateTime, default=datetime.utcnow, nullable=False)
    company                = relationship("CompanyORM", back_populates="recruiter_analytics")
    __table_args__ = (
        UniqueConstraint("company_id", "user_id", "period", name="uq_recruiter_period"),
        Index("idx_recruiter_company_period", "company_id", "period"),
    )

class SLAAlertORM(Base):
    __tablename__ = "sla_alerts"
    id           = Column(String(36), primary_key=True, index=True)
    alert_type   = Column(String(50), nullable=False, index=True)
    severity     = Column(String(20), nullable=False, index=True)
    message      = Column(Text, nullable=False)
    metric_value = Column(Float, nullable=True)
    threshold    = Column(Float, nullable=True)
    company_id   = Column(String(36), nullable=True, index=True)
    resolved     = Column(Boolean, default=False, index=True)
    resolved_at  = Column(DateTime, nullable=True)
    notified     = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

# ============================================================
# PHASE 31 — ENTERPRISE API + WEBHOOKS
# ============================================================

class APIKeyORM(Base):
    __tablename__ = "api_keys"
    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name         = Column(String(120), nullable=False)
    key_hash     = Column(String(64), unique=True, nullable=False, index=True)
    key_prefix   = Column(String(8), nullable=False)
    scopes       = Column(Text, nullable=False)
    rate_limit   = Column(Integer, default=60)
    last_used_at = Column(DateTime, nullable=True)
    total_calls  = Column(Integer, default=0)
    is_active    = Column(Boolean, default=True, index=True)
    is_deleted   = Column(Boolean, default=False, index=True)
    deleted_at   = Column(DateTime, nullable=True)
    expires_at   = Column(DateTime, nullable=True)
    created_by   = Column(String(36), nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    company      = relationship("CompanyORM", back_populates="api_keys")
    __table_args__ = (Index("idx_apikey_company_active", "company_id", "is_active"),)

class WebhookORM(Base):
    __tablename__ = "webhooks"
    id            = Column(String(36), primary_key=True, index=True)
    company_id    = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name          = Column(String(120), nullable=False)
    url           = Column(String(500), nullable=False)
    secret        = Column(String(64), nullable=False)
    event_types   = Column(Text, nullable=False)
    is_active     = Column(Boolean, default=True, index=True)
    is_deleted    = Column(Boolean, default=False, index=True)
    last_delivery = Column(DateTime, nullable=True)
    failure_count = Column(Integer, default=0)
    total_sent    = Column(Integer, default=0)
    created_by    = Column(String(36), nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    company       = relationship("CompanyORM", back_populates="webhooks")
    delivery_logs = relationship("WebhookDeliveryLogORM", back_populates="webhook", cascade="all, delete-orphan")
    __table_args__ = (Index("idx_webhook_company_active", "company_id", "is_active"),)

class WebhookDeliveryLogORM(Base):
    __tablename__ = "webhook_delivery_logs"
    id            = Column(String(36), primary_key=True, index=True)
    webhook_id    = Column(String(36), ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id    = Column(String(36), nullable=False, index=True)
    event_type    = Column(String(100), nullable=False, index=True)
    event_id      = Column(String(36), nullable=False)
    payload       = Column(Text, nullable=True)
    status        = Column(String(20), nullable=False, index=True)
    http_status   = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    error         = Column(Text, nullable=True)
    latency_ms    = Column(Float, nullable=True)
    attempt       = Column(Integer, default=1)
    next_retry_at = Column(DateTime, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    webhook       = relationship("WebhookORM", back_populates="delivery_logs")
    __table_args__ = (
        Index("idx_webhook_log_status", "webhook_id", "status"),
        Index("idx_webhook_log_event",  "webhook_id", "event_type"),
    )

class APIAuditLogORM(Base):
    __tablename__ = "api_audit_logs"
    id           = Column(Integer, primary_key=True, index=True)
    company_id   = Column(String(36), nullable=False, index=True)
    api_key_id   = Column(String(36), ForeignKey("api_keys.id"), nullable=True, index=True)
    endpoint     = Column(String(200), nullable=False, index=True)
    method       = Column(String(10), nullable=False)
    status_code  = Column(Integer, nullable=False)
    latency_ms   = Column(Float, nullable=True)
    cost_usd     = Column(Float, default=0.0)
    ip_address   = Column(String(50), nullable=True)
    user_agent   = Column(String(200), nullable=True)
    error        = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    __table_args__ = (
        Index("idx_audit_company_endpoint", "company_id", "endpoint"),
        Index("idx_audit_company_date",     "company_id", "created_at"),
    )

# ============================================================
# PHASE 32A — PARTNER INTEGRATIONS
# ============================================================

class PartnerSyncLogORM(Base):
    __tablename__ = "partner_sync_logs"
    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    partner      = Column(String(50),  nullable=False, index=True)
    direction    = Column(String(20),  nullable=False, index=True)
    event_type   = Column(String(100), nullable=False, index=True)
    payload      = Column(Text, nullable=True)
    normalized   = Column(Text, nullable=True)
    status       = Column(String(20), nullable=False, index=True)
    error        = Column(Text, nullable=True)
    latency_ms   = Column(Float, nullable=True)
    candidate_id  = Column(String(36), ForeignKey("company_candidates.id"), nullable=True, index=True)
    external_id   = Column(String(200), nullable=True)
    attempt       = Column(Integer, default=1)
    next_retry_at = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    company = relationship("CompanyORM", back_populates="partner_sync_logs")
    __table_args__ = (
        Index("idx_sync_company_partner",   "company_id", "partner"),
        Index("idx_sync_company_status",    "company_id", "status"),
        Index("idx_sync_company_direction", "company_id", "direction"),
    )

# ============================================================
# PHASE 32B — AI-GENERATED JOB DESCRIPTIONS
# ============================================================

class JobDescriptionORM(Base):
    __tablename__ = "job_descriptions"
    id               = Column(String(36), primary_key=True, index=True)
    company_id       = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id           = Column(String(36), ForeignKey("company_roles.id", ondelete="CASCADE"), nullable=True, index=True)
    content          = Column(Text, nullable=False)
    summary          = Column(Text, nullable=True)
    responsibilities = Column(Text, nullable=True)
    requirements     = Column(Text, nullable=True)
    benefits         = Column(Text, nullable=True)
    culture          = Column(Text, nullable=True)
    dei_statement    = Column(Text, nullable=True)
    tone             = Column(String(50), nullable=True)
    role_type        = Column(String(50), nullable=True)
    model_used       = Column(String(50), nullable=True)
    prompt_version   = Column(String(20), default="v32.1")
    tokens_used      = Column(Integer, nullable=True)
    cost_usd         = Column(Float, default=0.0)
    latency_ms       = Column(Float, nullable=True)
    version          = Column(Integer, default=1)
    is_active        = Column(Boolean, default=True)
    quality_score    = Column(Float, nullable=True)
    word_count       = Column(Integer, nullable=True)
    is_deleted       = Column(Boolean, default=False, index=True)
    deleted_at       = Column(DateTime, nullable=True)
    created_by       = Column(String(36), nullable=False)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    company = relationship("CompanyORM", back_populates="job_descriptions")
    job     = relationship("CompanyRoleORM", back_populates="job_descriptions")
    __table_args__ = (
        Index("idx_jd_company_job",    "company_id", "job_id"),
        Index("idx_jd_company_active", "company_id", "is_active"),
    )

# ============================================================
# PHASE 33 — RECRUITER OS + AI OUTREACH
# ============================================================

class PipelineStageORM(Base):
    """
    Pipeline stages for a recruiter project.
    Each project has ordered stages (sourcing → hired).
    Candidates move through stages in the kanban workspace.
    """
    __tablename__ = "pipeline_stages"

    id         = Column(String(36), primary_key=True, index=True)
    project_id = Column(String(36), ForeignKey("recruiter_projects.id"), nullable=False, index=True)
    name       = Column(String(100), nullable=False)   # e.g. Sourcing, Screening, Interview
    order      = Column(Integer, nullable=False)        # display order in kanban
    color      = Column(String(20), nullable=True)      # hex color for UI
    is_default = Column(Boolean, default=False)         # is this a default stage?

    project    = relationship("RecruiterProjectORM", back_populates="stages")
    candidates = relationship("ProjectCandidateORM", back_populates="stage")

    __table_args__ = (
        Index("idx_stage_project_order", "project_id", "order"),
    )

    def __repr__(self):
        return f"<PipelineStage {self.name} order={self.order}>"


class RecruiterProjectORM(Base):
    """
    Recruiter workspace projects — LinkedIn Recruiter Lite.
    Each project is a hiring pipeline for a specific role.
    Powers the workspace UI and recruiter copilot.
    Unlocks: workspace, app, analytics, collaboration, monetization.
    """
    __tablename__ = "recruiter_projects"

    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id      = Column(String(36), ForeignKey("company_roles.id"), nullable=True, index=True)
    created_by   = Column(String(36), nullable=False, index=True)

    # Project identity
    name         = Column(String(200), nullable=False)
    description  = Column(Text, nullable=True)
    status       = Column(String(50), default="active", index=True)  # active/paused/closed/hired
    priority     = Column(String(20), default="medium", index=True)  # low/medium/high/urgent

    # Pipeline stage
    stage        = Column(String(50), default="sourcing", index=True)
    # sourcing → screening → shortlisted → interviewing → offer → hired → closed

    # Targets
    target_hire_date  = Column(DateTime, nullable=True)
    target_candidates = Column(Integer, default=10)
    target_hires      = Column(Integer, default=1)

    # Metrics (auto-updated)
    total_candidates  = Column(Integer, default=0)
    shortlisted_count = Column(Integer, default=0)
    outreach_sent     = Column(Integer, default=0)
    responses_received = Column(Integer, default=0)
    interviews_scheduled = Column(Integer, default=0)
    offers_made       = Column(Integer, default=0)
    hires_made        = Column(Integer, default=0)

    # Collaboration
    is_shared        = Column(Boolean, default=False)   # shared with team
    shared_with      = Column(Text, nullable=True)      # JSON array of user_ids

    # Copilot
    copilot_enabled  = Column(Boolean, default=True)
    last_copilot_run = Column(DateTime, nullable=True)

    is_deleted  = Column(Boolean, default=False, index=True)
    deleted_at  = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company    = relationship("CompanyORM", back_populates="recruiter_projects")
    role       = relationship("CompanyRoleORM", back_populates="recruiter_projects")
    stages     = relationship("PipelineStageORM", back_populates="project", cascade="all, delete-orphan")
    candidates = relationship("ProjectCandidateORM", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_project_company_status",   "company_id", "status"),
        # idx_project_company_stage removed — stage column not present
        Index("idx_project_created_by",       "company_id", "created_by"),
    )

    def __repr__(self):
        return f"<RecruiterProject {self.name} status={self.status} stage={self.stage}>"


class ProjectCandidateORM(Base):
    """
    Candidates inside a recruiter project pipeline.
    Tracks stage, notes, and actions per candidate per project.
    Powers the kanban-style pipeline view.
    """
    __tablename__ = "project_candidates"

    id           = Column(String(36), primary_key=True, index=True)
    project_id   = Column(String(36), ForeignKey("recruiter_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id = Column(String(36), ForeignKey("company_candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_id     = Column(String(36), ForeignKey("pipeline_stages.id"), nullable=True, index=True)
    company_id   = Column(String(36), nullable=False, index=True)
    added_by     = Column(String(36), nullable=False)

    # Pipeline stage for this candidate in this project
    stage_name       = Column(String(50), default="sourcing", index=True)
    # sourcing → outreach_sent → responded → screening → shortlisted →
    # interviewing → offer → hired → rejected

    # Stage metadata
    stage_changed_at = Column(DateTime, nullable=True)
    stage_changed_by = Column(String(36), nullable=True)

    # Recruiter notes
    notes        = Column(Text, nullable=True)
    rating       = Column(Integer, nullable=True)   # 1-5 recruiter rating

    # Outreach tracking
    outreach_sent     = Column(Boolean, default=False)
    outreach_sent_at  = Column(DateTime, nullable=True)
    outreach_type     = Column(String(50), nullable=True)  # linkedin/email/inmail
    responded         = Column(Boolean, default=False)
    responded_at      = Column(DateTime, nullable=True)

    is_deleted   = Column(Boolean, default=False, index=True)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project   = relationship("RecruiterProjectORM", back_populates="candidates")
    candidate = relationship("CompanyCandidateORM", back_populates="project_candidates")
    stage     = relationship("PipelineStageORM", back_populates="candidates")

    __table_args__ = (
        UniqueConstraint("project_id", "candidate_id", name="uq_project_candidate"),
        Index("idx_pc_project_stage",     "project_id", "stage_name"),
        Index("idx_pc_company",           "company_id"),
    )

    def __repr__(self):
        return f"<ProjectCandidate project={self.project_id} candidate={self.candidate_id} stage={self.stage_name}>"


class OutreachORM(Base):
    """
    AI-generated outreach messages per candidate.
    LinkedIn connection requests, InMails, emails, follow-ups, rejections.
    Powered by GPT-4o + Phase 29 narrative engine integration.
    Phase 33-final — aligned with outreach_engine.py.
    """
    __tablename__ = "outreach_messages"

    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), ForeignKey("companies.id"), nullable=False, index=True)
    candidate_id = Column(String(36), ForeignKey("company_candidates.id"), nullable=False, index=True)
    project_id   = Column(String(36), ForeignKey("recruiter_projects.id"), nullable=True, index=True)

    # Core content
    message_type = Column(String(50), nullable=False, index=True)
    # linkedin_connection / linkedin_inmail / email / followup / rejection
    channel      = Column(String(50), nullable=False, index=True)  # linkedin/email
    subject      = Column(String(300), nullable=True)              # for email/inmail
    content      = Column(Text, nullable=False)                    # the actual message
    char_count   = Column(Integer, default=0)
    tone         = Column(String(50), default="warm")              # warm/professional/bold/concise

    # AI metadata
    personalization_score = Column(Float, default=0.0)
    quality_score         = Column(Float, default=0.0)
    model_used            = Column(String(50), nullable=True)
    prompt_version        = Column(String(20), default="v33.1")
    tokens_used           = Column(Integer, default=0)
    cost_usd              = Column(Float, default=0.0)
    latency_ms            = Column(Float, default=0.0)

    # Status tracking
    sent       = Column(Boolean, default=False, index=True)
    sent_at    = Column(DateTime, nullable=True)
    sent_via   = Column(String(50), nullable=True)   # linkedin/email/manual
    responded  = Column(Boolean, default=False)
    responded_at = Column(DateTime, nullable=True)

    # System
    created_by = Column(String(36), nullable=False, index=True)
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    company   = relationship("CompanyORM", back_populates="outreach_messages")
    candidate = relationship("CompanyCandidateORM", back_populates="outreach_messages")

    __table_args__ = (
        Index("idx_outreach_company_type", "company_id", "message_type"),
        Index("idx_outreach_candidate",    "candidate_id"),
        Index("idx_outreach_company_sent", "company_id", "sent"),
    )

    def __repr__(self):
        return f"<Outreach {self.message_type} candidate={self.candidate_id} sent={self.sent}>"


class RecruiterCopilotORM(Base):
    """
    AI Recruiter Copilot sessions.
    Provides intelligent insights inside the workspace.
    Powers: candidate recommendations, pipeline health, hiring predictions.
    """
    __tablename__ = "recruiter_copilot_sessions"

    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id      = Column(String(36), nullable=False, index=True)
    project_id   = Column(String(36), ForeignKey("recruiter_projects.id"), nullable=True, index=True)

    # Session type
    session_type = Column(String(50), nullable=False, index=True)
    # pipeline_health / candidate_recommendation / hiring_prediction /
    # outreach_optimization / market_insight / next_best_action

    # Copilot conversation
    prompt       = Column(Text, nullable=False)   # recruiter's question/context
    response     = Column(Text, nullable=False)   # AI copilot response

    # Input context
    context      = Column(Text, nullable=True)    # JSON — what was analyzed

    # Copilot output
    insights        = Column(Text, nullable=True)  # structured AI insights
    recommendations = Column(Text, nullable=True)  # JSON array of actions
    confidence      = Column(Float, nullable=True) # 0-1

    # Generation metadata
    model_version = Column(String(20), default="gpt-4o")
    tokens_used   = Column(Integer, nullable=True)
    cost_usd      = Column(Float, default=0.0)
    latency_ms    = Column(Float, nullable=True)

    # Feedback
    helpful      = Column(Boolean, nullable=True)  # recruiter thumbs up/down
    acted_on     = Column(Boolean, default=False)  # did recruiter act on it

    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    company = relationship("CompanyORM", back_populates="copilot_sessions")

    __table_args__ = (
        Index("idx_copilot_company_type",    "company_id", "session_type"),
        Index("idx_copilot_company_user",    "company_id", "user_id"),
        Index("idx_copilot_project",         "project_id"),
    )

    def __repr__(self):
        return f"<RecruiterCopilot {self.session_type} user={self.user_id}>"


# ============================================================
# TEAM DNA — score candidates against a company's OWN best people
# (additive; nothing above this block changed)
#
# Tenancy: company_id IS the tenant boundary and the only thing queries filter
# on — Team DNA is a property of the company's team, so colleagues share one
# model per role. user_id is still recorded on every row for audit (who added
# this exemplar, who gave this verdict) but is never used to scope a read.
# ============================================================

class TeamDNAProfileORM(Base):
    """One exemplar employee uploaded by a recruiter as an example of 'good'."""
    __tablename__ = "team_dna_profiles"

    id         = Column(String(36), primary_key=True, index=True)
    company_id = Column(String(36), nullable=False, index=True)
    user_id    = Column(String(36), nullable=False, index=True)   # audit: who added it
    role_id    = Column(String(36), nullable=False, index=True)

    name       = Column(String(200), nullable=False)
    raw_text   = Column(Text, nullable=False)
    source     = Column(String(50), default="paste")   # paste | pdf | docx | txt

    is_deleted = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_tdna_profile_scope", "company_id", "role_id"),
    )

    def __repr__(self):
        return f"<TeamDNAProfile {self.name} role={self.role_id}>"


class TeamDNAModelORM(Base):
    """The extracted 'what good looks like' model for one user+role."""
    __tablename__ = "team_dna_models"

    id         = Column(String(36), primary_key=True, index=True)
    company_id = Column(String(36), nullable=False, index=True)
    user_id    = Column(String(36), nullable=False, index=True)
    role_id    = Column(String(36), nullable=False, index=True)

    extracted_traits = Column(Text, nullable=False)     # JSON blob
    summary          = Column(Text, nullable=True)

    # Fingerprint of the profile set this model was built from. When the set
    # changes the fingerprint changes and the cache is rebuilt — nothing else.
    source_fingerprint = Column(String(64), nullable=True, index=True)
    profile_count      = Column(Integer, default=0)
    model_used         = Column(String(50), nullable=True)
    latency_ms         = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # One shared model per company+role. user_id records who last built it.
        UniqueConstraint("company_id", "role_id", name="uq_team_dna_model_scope"),
        Index("idx_tdna_model_scope", "company_id", "role_id"),
    )

    def __repr__(self):
        return f"<TeamDNAModel role={self.role_id} profiles={self.profile_count}>"


class CandidateFeedbackORM(Base):
    """Recruiter good/bad verdicts, replayed into later prompts as calibration."""
    __tablename__ = "candidate_feedback"

    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), nullable=False, index=True)
    user_id      = Column(String(36), nullable=False, index=True)
    role_id      = Column(String(36), nullable=False, index=True)
    candidate_id = Column(String(36), nullable=False, index=True)

    verdict      = Column(String(10), nullable=False, index=True)   # 'good' | 'bad'
    reason       = Column(Text, nullable=True)
    candidate_name = Column(String(200), nullable=True)

    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_cand_feedback_scope", "company_id", "role_id", "created_at"),
    )

    def __repr__(self):
        return f"<CandidateFeedback {self.verdict} candidate={self.candidate_id}>"


# ============================================================
# HIRING OUTCOMES — what actually happened to each scored candidate
# (additive; nothing above this block changed)
#
# This is the dataset that makes scoring accountable: the ORIGINAL score,
# frozen at the moment it was first recorded, paired with the real-world
# result. It cannot be reconstructed later, which is why score_at_time is
# written once and never updated.
#
# Tenancy: company_id is the boundary and the only thing queries filter on,
# matching the Team DNA convention. user_id is recorded for audit.
# ============================================================

class CandidateOutcomeORM(Base):
    """The real-world result of one scored candidate."""
    __tablename__ = "candidate_outcomes"

    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), nullable=False, index=True)
    user_id      = Column(String(36), nullable=False, index=True)   # audit: who recorded it
    role_id      = Column(String(36), nullable=False, index=True)
    candidate_id = Column(String(36), nullable=False, index=True)

    # Frozen at first write. Never updated — correlating the ORIGINAL score to
    # the eventual outcome is the entire point of this table.
    score_at_time = Column(Float, nullable=True)
    tier_at_time  = Column(String(20), nullable=True, index=True)

    # Current stage.
    stage = Column(String(20), nullable=False, default="sourced", index=True)
    # sourced → contacted → screened → interviewed → offered → hired
    # rejected / withdrawn are terminal and can happen from any stage.

    # The furthest point this candidate ever reached, kept separately because
    # `stage` moves BACKWARDS on rejection. Without this, a candidate who was
    # interviewed and then rejected would not count toward "% reached
    # interview" — which would understate the funnel for exactly the
    # candidates the funnel is meant to measure.
    furthest_stage = Column(String(20), nullable=False, default="sourced", index=True)

    rejected_reason = Column(Text, nullable=True)
    hired_at        = Column(DateTime, nullable=True, index=True)

    # 12-month retention follow-up.
    still_employed_check_at = Column(DateTime, nullable=True)
    still_employed          = Column(Boolean, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # One outcome row per candidate per role.
        UniqueConstraint("company_id", "role_id", "candidate_id", name="uq_candidate_outcome"),
        Index("idx_outcome_scope", "company_id", "role_id"),
        Index("idx_outcome_band", "company_id", "score_at_time"),
    )

    def __repr__(self):
        return f"<CandidateOutcome {self.candidate_id} stage={self.stage} score={self.score_at_time}>"


# ============================================================
# PARTNER (ATS) CREDENTIALS
#
# A customer's Greenhouse/Lever API key belongs on the server, not in
# localStorage and not re-sent from the browser on every push. Stored
# encrypted at rest; never returned to the client — reads get a masked hint
# only, so the UI can show "connected as yourcompany" without handing the
# secret back out.
# ============================================================

class PartnerCredentialORM(Base):
    __tablename__ = "partner_credentials"

    id          = Column(String(36), primary_key=True, index=True)
    company_id  = Column(String(36), nullable=False, index=True)
    user_id     = Column(String(36), nullable=False)      # audit: who connected it
    partner     = Column(String(30), nullable=False, index=True)   # greenhouse | lever

    account_ref = Column(String(200), nullable=True)      # subdomain / account id — not secret
    secret_enc  = Column(Text, nullable=False)            # Fernet-encrypted API key
    key_hint    = Column(String(20), nullable=True)       # last 4 chars, for display only

    is_active   = Column(Boolean, default=True, index=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("company_id", "partner", name="uq_company_partner_credential"),
    )

    def __repr__(self):
        return f"<PartnerCredential {self.partner} company={self.company_id}>"


# ============================================================
# DATABASE INIT
# ============================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _run_lightweight_migrations():
    """Additive column adds for SQLite — create_all() creates missing TABLES but never
    ALTERs existing ones, so new columns on already-created tables are added here (idempotent)."""
    import logging
    _adds = [("company_users", "email_verified", "BOOLEAN DEFAULT 0"),
             ("company_users", "linkedin_url", "VARCHAR(300)"),
             ("company_users", "job_title", "VARCHAR(120)"),
             ("companies", "trial_ends_at", "DATETIME"),
             ("companies", "trial_reminder_sent", "BOOLEAN DEFAULT 0"),
             # Per-role archiving — company_roles predates this, so create_all()
             # cannot add these and they must be ALTERed in.
             ("company_roles", "is_archived", "BOOLEAN DEFAULT 0"),
             ("company_roles", "archived_at", "DATETIME")]
    try:
        with engine.begin() as conn:
            for table, col, coldef in _adds:
                existing = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]
                if existing and col not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {coldef}")
                    logging.getLogger(__name__).info("migration: added %s.%s", table, col)
    except Exception as e:
        logging.getLogger(__name__).warning("lightweight migration skipped: %s", e)

def init_db():
    Base.metadata.create_all(bind=engine, checkfirst=True)
    _run_lightweight_migrations()

# ============================================================
# PHASE 34 — AI INTERVIEW QUESTIONS
# ============================================================

class InterviewQuestionSetORM(Base):
    """
    AI-generated interview question sets per candidate + role.
    Powered by GPT-4o. Questions are tiered by difficulty
    and category, tailored to the specific candidate profile.
    """
    __tablename__ = "interview_question_sets"

    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id = Column(String(36), ForeignKey("company_candidates.id"), nullable=False, index=True)
    job_id       = Column(String(36), ForeignKey("company_roles.id"), nullable=True, index=True)
    created_by   = Column(String(36), nullable=False)

    # Questions stored as JSON array
    questions_json  = Column(Text, nullable=False)
    question_count  = Column(Integer, default=0)
    focus_areas     = Column(String(500), nullable=True)  # e.g. "leadership,python"

    # Generation metadata
    model_used      = Column(String(50), nullable=True)
    prompt_version  = Column(String(20), default="v34.1")
    tokens_used     = Column(Integer, nullable=True)
    cost_usd        = Column(Float, default=0.0)
    latency_ms      = Column(Float, nullable=True)
    tier            = Column(String(20), nullable=True, index=True)

    # Quality
    used_in_interview = Column(Boolean, default=False)
    interviewer_rating = Column(Float, nullable=True)  # 1-5

    is_deleted  = Column(Boolean, default=False, index=True)
    deleted_at  = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_interview_company_candidate", "company_id", "candidate_id"),
        Index("idx_interview_company_tier",      "company_id", "tier"),
    )

    def __repr__(self):
        return f"<InterviewQuestionSet candidate={self.candidate_id} count={self.question_count}>"

# ============================================================
# PHASE 34 — FULL INTELLIGENCE LAYER (all 12 steps)
# ============================================================

class IntelligenceSnapshotORM(Base):
    """Step 1 — Daily time-series snapshots for trend analysis."""
    __tablename__ = "intelligence_snapshots"
    id               = Column(String(36), primary_key=True, index=True)
    company_id       = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_date    = Column(DateTime, nullable=False, index=True)
    total_candidates = Column(Integer, default=0)
    gold_count       = Column(Integer, default=0)
    silver_count     = Column(Integer, default=0)
    bronze_count     = Column(Integer, default=0)
    avg_match_score  = Column(Float, default=0.0)
    outreach_sent    = Column(Integer, default=0)
    outreach_replied = Column(Integer, default=0)
    response_rate    = Column(Float, default=0.0)
    shortlisted_count = Column(Integer, default=0)
    copilot_sessions = Column(Integer, default=0)
    active_projects  = Column(Integer, default=0)
    score_drift      = Column(Float, default=0.0)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("company_id", "snapshot_date", name="uq_snapshot_company_date"),)
    def __repr__(self): return f"<IntelligenceSnapshot {self.company_id} {self.snapshot_date}>"

class IntelligenceForecastORM(Base):
    """Step 2 — Predictive model outputs stored for caching."""
    __tablename__ = "intelligence_forecasts"
    id                       = Column(String(36), primary_key=True, index=True)
    company_id               = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id               = Column(String(36), nullable=True, index=True)
    forecast_date            = Column(DateTime, nullable=False, index=True)
    est_time_to_hire_days    = Column(Float, nullable=True)
    response_probability     = Column(Float, nullable=True)
    fit_success_probability  = Column(Float, nullable=True)
    outreach_success_prob    = Column(Float, nullable=True)
    pipeline_stall_risk      = Column(String(20), nullable=True)
    stall_in_days            = Column(Integer, nullable=True)
    outreach_volume_needed   = Column(Integer, nullable=True)
    score_volatility         = Column(Float, nullable=True)
    momentum_score           = Column(Float, nullable=True)
    momentum_label           = Column(String(30), nullable=True)
    momentum_direction       = Column(String(20), nullable=True)
    created_at               = Column(DateTime, default=datetime.utcnow, nullable=False)
    def __repr__(self): return f"<IntelligenceForecast {self.company_id} {self.forecast_date}>"

class IntelligenceNarrativeORM(Base):
    """Step 3 — AI analyst narratives."""
    __tablename__ = "intelligence_narratives"
    id             = Column(String(36), primary_key=True, index=True)
    company_id     = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    narrative_type = Column(String(50), nullable=False, index=True)
    narrative      = Column(Text, nullable=False)
    context_json   = Column(Text, nullable=True)
    model_used     = Column(String(50), nullable=True)
    tokens_used    = Column(Integer, nullable=True)
    cost_usd       = Column(Float, default=0.0)
    latency_ms     = Column(Float, nullable=True)
    helpful        = Column(Boolean, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    def __repr__(self): return f"<IntelligenceNarrative {self.narrative_type}>"

class IntelligenceActionORM(Base):
    """Step 5 — Next-best-action recommendations."""
    __tablename__ = "intelligence_actions"
    id         = Column(String(36), primary_key=True, index=True)
    company_id = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), nullable=True, index=True)
    action     = Column(Text, nullable=False)
    impact     = Column(Text, nullable=True)
    urgency    = Column(String(20), nullable=True, index=True)
    category   = Column(String(50), nullable=True, index=True)
    rank       = Column(Integer, default=1)
    acted_on   = Column(Boolean, default=False)
    outcome    = Column(Text, nullable=True)
    model_used = Column(String(50), nullable=True)
    tokens_used = Column(Integer, nullable=True)
    cost_usd   = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    def __repr__(self): return f"<IntelligenceAction {self.urgency} {self.category}>"

class IntelligenceAlertORM(Base):
    """Step 8 — Real-time alerts and triggers."""
    __tablename__ = "intelligence_alerts"
    id          = Column(String(36), primary_key=True, index=True)
    company_id  = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    alert_type  = Column(String(50), nullable=False, index=True)
    message     = Column(Text, nullable=False)
    severity    = Column(String(20), nullable=False, index=True)
    resolved    = Column(Boolean, default=False, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(36), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    __table_args__ = (Index("idx_alert_company_resolved", "company_id", "resolved"),)
    def __repr__(self): return f"<IntelligenceAlert {self.alert_type} {self.severity}>"

class IntelligenceDigestORM(Base):
    """Step 7 — Weekly AI-generated executive digest."""
    __tablename__ = "intelligence_digests"
    id          = Column(String(36), primary_key=True, index=True)
    company_id  = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    week_start  = Column(DateTime, nullable=False, index=True)
    week_end    = Column(DateTime, nullable=False)
    digest_json = Column(Text, nullable=False)
    sent_email  = Column(Boolean, default=False)
    model_used  = Column(String(50), nullable=True)
    tokens_used = Column(Integer, nullable=True)
    cost_usd    = Column(Float, default=0.0)
    latency_ms  = Column(Float, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    def __repr__(self): return f"<IntelligenceDigest {self.company_id} {self.week_start}>"

class IntelligenceSettingsORM(Base):
    """Step 11 — Per-company intelligence configuration."""
    __tablename__ = "intelligence_settings"
    id                   = Column(String(36), primary_key=True, index=True)
    company_id           = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    alert_frequency      = Column(String(20), default="realtime")
    digest_frequency     = Column(String(20), default="weekly")
    action_intensity     = Column(String(20), default="balanced")
    forecast_sensitivity = Column(String(20), default="medium")
    risk_threshold       = Column(Float, default=0.3)
    linkedin_weight      = Column(Float, default=1.0)
    email_weight         = Column(Float, default=0.8)
    inmail_weight        = Column(Float, default=1.2)
    updated_at           = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at           = Column(DateTime, default=datetime.utcnow, nullable=False)
    def __repr__(self): return f"<IntelligenceSettings {self.company_id}>"

class IntelligenceAuditLogORM(Base):
    """Step 12 — Self-improvement audit trail."""
    __tablename__ = "intelligence_audit_logs"
    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    feature      = Column(String(50), nullable=False, index=True)
    action       = Column(String(50), nullable=False, index=True)
    details_json = Column(Text, nullable=True)
    outcome      = Column(Text, nullable=True)
    accurate     = Column(Boolean, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    __table_args__ = (Index("idx_audit_intel_company_feature", "company_id", "feature"),)
    def __repr__(self): return f"<IntelligenceAudit {self.feature} {self.action}>"

class RecruiterPerformanceORM(Base):
    """Step 6 — Per-recruiter performance metrics."""
    __tablename__ = "recruiter_performance"
    id               = Column(String(36), primary_key=True, index=True)
    company_id       = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id          = Column(String(36), nullable=False, index=True)
    user_name        = Column(String(120), nullable=True)
    period           = Column(String(7), nullable=False, index=True)
    outreach_volume  = Column(Integer, default=0)
    response_rate    = Column(Float, default=0.0)
    shortlist_quality = Column(Float, default=0.0)
    time_to_action   = Column(Float, nullable=True)
    copilot_sessions = Column(Integer, default=0)
    efficiency_score = Column(Float, default=0.0)
    wow_delta        = Column(Float, nullable=True)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("company_id", "user_id", "period", name="uq_recruiter_perf_period"),
        Index("idx_recruiter_perf_company", "company_id", "period"),
    )
    def __repr__(self): return f"<RecruiterPerformance {self.user_id} {self.period}>"

# ============================================================
# PHASE 35 — AI SCORECARDS
# ============================================================

class ScorecardORM(Base):
    """AI + Human collaborative scorecard per candidate per role."""
    __tablename__ = "scorecards"

    id                   = Column(String(36), primary_key=True, index=True)
    company_id           = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id         = Column(String(36), ForeignKey("company_candidates.id"), nullable=False, index=True)
    job_id               = Column(String(36), nullable=True, index=True)
    project_id           = Column(String(36), nullable=True, index=True)
    created_by           = Column(String(36), nullable=False)

    # AI scorecard data
    scorecard_json       = Column(Text, nullable=False)
    dimensions_json      = Column(Text, nullable=True)
    overall_score        = Column(Float, nullable=True)
    recommendation       = Column(String(20), nullable=True, index=True)
    recommendation_label = Column(String(30), nullable=True)
    summary              = Column(Text, nullable=True)
    strengths_json       = Column(Text, nullable=True)
    concerns_json        = Column(Text, nullable=True)
    vs_ai_score_json     = Column(Text, nullable=True)
    ai_match_score       = Column(Float, nullable=True)
    focus_areas          = Column(String(500), nullable=True)

    # Human scoring (collaborative)
    human_scores_json    = Column(Text, nullable=True)
    avg_human_score      = Column(Float, nullable=True)
    human_scorer_count   = Column(Integer, default=0)

    # Generation metadata
    model_used           = Column(String(50), nullable=True)
    prompt_version       = Column(String(20), default="v35.1")
    tokens_used          = Column(Integer, nullable=True)
    cost_usd             = Column(Float, default=0.0)
    latency_ms           = Column(Float, nullable=True)
    is_fallback          = Column(Boolean, default=False)

    is_deleted           = Column(Boolean, default=False, index=True)
    deleted_at           = Column(DateTime, nullable=True)
    created_at           = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at           = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_scorecard_company_candidate", "company_id", "candidate_id"),
        Index("idx_scorecard_recommendation",    "company_id", "recommendation"),
    )

    def __repr__(self):
        return f"<Scorecard candidate={self.candidate_id} score={self.overall_score}>"

# ============================================================
# PHASE 37 — FORECAST 2.0 + RECRUITER OS
# ============================================================

class ForecastCacheORM(Base):
    __tablename__ = "forecast_cache"
    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id   = Column(String(36), nullable=True, index=True)
    cache_key    = Column(String(200), nullable=False, index=True)
    forecast_json = Column(Text, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at   = Column(DateTime, nullable=False)
    is_deleted   = Column(Boolean, default=False)

class ScenarioLogORM(Base):
    __tablename__ = "scenario_logs"
    id             = Column(String(36), primary_key=True, index=True)
    company_id     = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id     = Column(String(36), nullable=True)
    inputs_json    = Column(Text, nullable=False)
    outputs_json   = Column(Text, nullable=False)
    cost_usd       = Column(Float, default=0.0)
    latency_ms     = Column(Float, default=0.0)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)

class FunnelStatsORM(Base):
    __tablename__ = "funnel_stats"
    id             = Column(String(36), primary_key=True, index=True)
    company_id     = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id     = Column(String(36), nullable=True, index=True)
    stage_name     = Column(String(100), nullable=False)
    predicted_count = Column(Integer, default=0)
    actual_count   = Column(Integer, default=0)
    drop_off_pct   = Column(Float, default=0.0)
    conversion_pct = Column(Float, default=0.0)
    avg_time_days  = Column(Float, default=0.0)
    is_bottleneck  = Column(Boolean, default=False)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ============================================================
# PHASE 38 — REAL-TIME CANDIDATE SIGNALS
# ============================================================

class CandidateSignalORM(Base):
    __tablename__ = "candidate_signals"

    id               = Column(String(36), primary_key=True, index=True)
    company_id       = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    candidate_id     = Column(String(36), nullable=False, index=True)
    job_id           = Column(String(36), nullable=True)
    signal_type      = Column(String(50), nullable=False, index=True)
    # signal_type options:
    # viewed_profile, updated_experience, new_skill, job_change,
    # open_to_work, recruiter_message_seen, recruiter_message_replied,
    # interest_spike, risk_signal, profile_update
    metadata_json    = Column(Text, nullable=True)
    confidence_score = Column(Float, default=0.8)
    is_read          = Column(Boolean, default=False)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_signal_company_candidate", "company_id", "candidate_id"),
        Index("idx_signal_company_type",      "company_id", "signal_type"),
        Index("idx_signal_created_at",        "company_id", "created_at"),
    )

# ============================================================
# PHASE 39 — AI RECRUITER COACHING + SSO
# ============================================================

class RecruiterCoachingEventORM(Base):
    __tablename__ = "recruiter_coaching_events"

    id            = Column(String(36), primary_key=True, index=True)
    company_id    = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id       = Column(String(36), nullable=False, index=True)
    candidate_id  = Column(String(36), nullable=True)
    job_id        = Column(String(36), nullable=True)
    coaching_type = Column(String(50), nullable=False, index=True)
    message       = Column(Text, nullable=False)
    severity      = Column(String(20), default="suggestion", index=True)
    metadata_json = Column(Text, nullable=True)
    is_read       = Column(Boolean, default=False)
    is_applied    = Column(Boolean, default=False)
    coaching_score = Column(Float, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_coaching_company_user", "company_id", "user_id"),
        Index("idx_coaching_type",         "company_id", "coaching_type"),
    )

class SSOProviderORM(Base):
    __tablename__ = "sso_providers"

    id            = Column(String(36), primary_key=True, index=True)
    company_id    = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    provider      = Column(String(30), nullable=False)  # azure_ad, google, okta
    tenant_id     = Column(String(200), nullable=True)
    client_id     = Column(String(200), nullable=True)
    client_secret = Column(String(500), nullable=True)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SSOSessionORM(Base):
    __tablename__ = "sso_sessions"

    id          = Column(String(36), primary_key=True, index=True)
    company_id  = Column(String(36), nullable=False, index=True)
    user_id     = Column(String(36), nullable=False, index=True)
    provider    = Column(String(30), nullable=False)
    sso_user_id = Column(String(200), nullable=True)
    email       = Column(String(200), nullable=True)
    ip_address  = Column(String(50), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at  = Column(DateTime, nullable=True)

# ============================================================
# PHASE 41 — POST-ACQUISITION INTEGRATION
# ============================================================

class WebhookDLQORM(Base):
    __tablename__ = "webhook_dlq"
    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), nullable=False, index=True)
    webhook_id   = Column(String(36), nullable=False, index=True)
    event_type   = Column(String(100), nullable=False)
    payload_json = Column(Text, nullable=False)
    error        = Column(Text, nullable=True)
    attempts     = Column(Integer, default=0)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    replayed_at  = Column(DateTime, nullable=True)

class ComplianceLogORM(Base):
    __tablename__ = "compliance_logs"
    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), nullable=False, index=True)
    user_id      = Column(String(36), nullable=True)
    action       = Column(String(100), nullable=False, index=True)
    resource     = Column(String(100), nullable=True)
    resource_id  = Column(String(100), nullable=True)
    ip_address   = Column(String(50), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

class PartnerInstallORM(Base):
    __tablename__ = "partner_installs"
    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), nullable=False, index=True)
    partner_key  = Column(String(50), nullable=False)
    config_json  = Column(Text, nullable=True)
    is_active    = Column(Boolean, default=True)
    installed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    uninstalled_at = Column(DateTime, nullable=True)

class MobileSessionORM(Base):
    __tablename__ = "mobile_sessions"
    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), nullable=False, index=True)
    user_id      = Column(String(36), nullable=False, index=True)
    token        = Column(String(200), nullable=False, unique=True, index=True)
    platform     = Column(String(20), nullable=True)  # ios, android
    device_id    = Column(String(200), nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at   = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)

# ============================================================
# PHASE 42 — GLOBAL ROLLOUT MODE
# ============================================================

class FeatureFlagORM(Base):
    __tablename__ = "feature_flags"
    id           = Column(String(36), primary_key=True, index=True)
    flag_key     = Column(String(100), nullable=False, unique=True, index=True)
    description  = Column(Text, nullable=True)
    is_enabled   = Column(Boolean, default=False)
    rollout_pct  = Column(Float, default=0.0)   # 0-100
    company_ids  = Column(Text, nullable=True)   # JSON list of specific companies
    regions      = Column(Text, nullable=True)   # JSON list of regions
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AIModelRouteORM(Base):
    __tablename__ = "ai_model_routes"
    id           = Column(String(36), primary_key=True, index=True)
    company_id   = Column(String(36), nullable=True, index=True)
    action       = Column(String(100), nullable=False, index=True)
    model        = Column(String(100), nullable=False)
    region       = Column(String(50), nullable=True)
    fallback     = Column(String(100), nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

class LinkedInOAuthORM(Base):
    __tablename__ = "linkedin_oauth"
    id              = Column(String(36), primary_key=True, index=True)
    company_id      = Column(String(36), nullable=False, index=True)
    user_id         = Column(String(36), nullable=False, index=True)
    linkedin_id     = Column(String(200), nullable=True)
    access_token    = Column(String(500), nullable=True)
    refresh_token   = Column(String(500), nullable=True)
    profile_data    = Column(Text, nullable=True)
    expires_at      = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)

class StatusPageORM(Base):
    __tablename__ = "status_events"
    id           = Column(String(36), primary_key=True, index=True)
    title        = Column(String(200), nullable=False)
    message      = Column(Text, nullable=False)
    status       = Column(String(30), nullable=False)  # operational, degraded, outage, maintenance
    component    = Column(String(100), nullable=True)
    region       = Column(String(50), nullable=True)
    resolved     = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at  = Column(DateTime, nullable=True)

# ============================================================
# PHASE 43 — TALENT GRAPH ENGINE + BILLING
# ============================================================

class GraphNodeORM(Base):
    __tablename__ = "graph_nodes"
    id            = Column(String(36), primary_key=True, index=True)
    company_id    = Column(String(36), nullable=False, index=True)
    node_type     = Column(String(50), nullable=False, index=True)  # candidate, role, skill, recruiter, company
    entity_id     = Column(String(36), nullable=False, index=True)
    metadata_json = Column(Text, nullable=True)
    embedding_json = Column(Text, nullable=True)  # stub vector
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_graph_company_type", "company_id", "node_type"),
        Index("idx_graph_entity",       "company_id", "entity_id"),
    )

class GraphEdgeORM(Base):
    __tablename__ = "graph_edges"
    id          = Column(String(36), primary_key=True, index=True)
    company_id  = Column(String(36), nullable=False, index=True)
    source_id   = Column(String(36), nullable=False, index=True)
    target_id   = Column(String(36), nullable=False, index=True)
    relation    = Column(String(50), nullable=False, index=True)
    weight      = Column(Float, default=1.0)
    metadata_json = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_edge_source",   "company_id", "source_id"),
        Index("idx_edge_target",   "company_id", "target_id"),
        Index("idx_edge_relation", "company_id", "relation"),
    )

class BillingEventORM(Base):
    __tablename__ = "billing_events"
    id              = Column(String(36), primary_key=True, index=True)
    company_id      = Column(String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type      = Column(String(100), nullable=False, index=True)
    stripe_event_id = Column(String(200), nullable=True, unique=True)
    amount_cents    = Column(Integer, default=0)
    currency        = Column(String(10), default="usd")
    metadata_json   = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)