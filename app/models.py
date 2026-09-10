# ============================================================
# AI Talent Match Pro — Models
# Phase 22: Enterprise SaaS Layer
# Company Accounts · RBAC · Team · Billing · Analytics
# ============================================================

from pydantic import BaseModel, Field, EmailStr
from datetime import datetime
from typing import Optional, List, Literal
from enum import Enum

# ============================================================
# EXISTING MODELS (unchanged)
# ============================================================

class IdeaCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=2000)
    author: Optional[str] = None

class Idea(BaseModel):
    id: int
    title: str
    description: str
    author: Optional[str] = None
    timestamp: datetime

class ProjectCreate(BaseModel):
    name: str
    status: str
    owner: Optional[str] = None

class Project(BaseModel):
    id: int
    name: str
    status: str
    owner: Optional[str] = None
    created_at: datetime

class QuestionCreate(BaseModel):
    question_text: str = Field(min_length=2, max_length=4000)
    user: Optional[str] = None

class Answer(BaseModel):
    id: int
    question_text: str
    user: Optional[str]
    timestamp: datetime
    answer: str

# ============================================================
# PHASE 22 — ENUMS
# ============================================================

class UserRole(str, Enum):
    admin     = "admin"      # Full access: billing, seats, settings
    recruiter = "recruiter"  # Full sourcing + scoring access
    viewer    = "viewer"     # Read-only access to candidates

class PlanType(str, Enum):
    free       = "free"        # 1 user, 1 candidate/search
    business   = "business"    # 5 users, 2 candidates/search
    corporate  = "corporate"   # 20 users, 3 candidates/search
    enterprise = "enterprise"  # Unlimited users, 50 candidates/search

class InviteStatus(str, Enum):
    pending  = "pending"
    accepted = "accepted"
    expired  = "expired"

class SubscriptionStatus(str, Enum):
    active   = "active"
    past_due = "past_due"
    canceled = "canceled"
    trialing = "trialing"

# ============================================================
# PHASE 22 — COMPANY ACCOUNTS (Multi-Tenant)
# ============================================================

class CompanyCreate(BaseModel):
    """Create a new company account."""
    name:    str = Field(min_length=2, max_length=120)
    domain:  str = Field(min_length=3, max_length=120)  # e.g. "acme.com"
    plan:    PlanType = PlanType.free
    admin_email: str
    admin_name:  str

class Company(BaseModel):
    """Full company object."""
    id:           str
    name:         str
    domain:       str
    plan:         PlanType
    seat_count:   int = 1
    seat_limit:   int = 1
    api_key:      str
    stripe_customer_id: Optional[str] = None
    created_at:   datetime
    updated_at:   datetime
    is_active:    bool = True

class CompanyUpdate(BaseModel):
    """Update company settings."""
    name:       Optional[str] = None
    plan:       Optional[PlanType] = None
    seat_limit: Optional[int] = None
    is_active:  Optional[bool] = None

class CompanyStats(BaseModel):
    """Company usage statistics."""
    company_id:       str
    total_searches:   int = 0
    total_candidates: int = 0
    total_shortlists: int = 0
    ai_calls_month:   int = 0
    ai_calls_limit:   int = 100
    active_users:     int = 0
    last_active:      Optional[datetime] = None

# ============================================================
# PHASE 22 — USERS + RBAC
# ============================================================

class UserCreate(BaseModel):
    """Create a new user."""
    email:      str
    name:       str
    company_id: str
    role:       UserRole = UserRole.recruiter
    password:   str = Field(min_length=8)

class User(BaseModel):
    """Full user object."""
    id:         str
    email:      str
    name:       str
    company_id: str
    role:       UserRole
    is_active:  bool = True
    photo:      Optional[str] = None
    last_login: Optional[datetime] = None
    created_at: datetime

class UserUpdate(BaseModel):
    """Update user profile or role."""
    name:      Optional[str] = None
    role:      Optional[UserRole] = None
    is_active: Optional[bool] = None
    photo:     Optional[str] = None

class UserLogin(BaseModel):
    """Login request."""
    email:    str
    password: str

class UserLoginResponse(BaseModel):
    """Login response with token."""
    token:      str
    user:       User
    company:    Company

class TokenData(BaseModel):
    """JWT token payload."""
    user_id:    str
    company_id: str
    role:       UserRole
    exp:        datetime

# ============================================================
# PHASE 22 — TEAM MANAGEMENT
# ============================================================

class TeamInviteCreate(BaseModel):
    """Send a team invitation."""
    email:      str
    role:       UserRole = UserRole.recruiter
    company_id: str
    invited_by: str  # user_id of admin

class TeamInvite(BaseModel):
    """Full invitation object."""
    id:          str
    email:       str
    role:        UserRole
    company_id:  str
    invited_by:  str
    status:      InviteStatus = InviteStatus.pending
    token:       str
    expires_at:  datetime
    created_at:  datetime

class TeamInviteAccept(BaseModel):
    """Accept an invitation."""
    token:    str
    name:     str
    password: str = Field(min_length=8)

class TeamMember(BaseModel):
    """Team member summary."""
    id:         str
    email:      str
    name:       str
    role:       UserRole
    is_active:  bool
    last_login: Optional[datetime] = None
    joined_at:  datetime

class TeamList(BaseModel):
    """List of team members."""
    company_id: str
    members:    List[TeamMember]
    total:      int
    seat_used:  int
    seat_limit: int

# ============================================================
# PHASE 22 — BILLING + STRIPE
# ============================================================

class PlanDetails(BaseModel):
    """Plan configuration."""
    plan:              PlanType
    name:              str
    price_monthly:     float
    price_annual:      float
    seat_limit:        int
    candidates_per_search: int
    ai_calls_per_month: int
    features:          List[str]

class SubscriptionCreate(BaseModel):
    """Create a subscription."""
    company_id:      str
    plan:            PlanType
    billing_cycle:   Literal["monthly", "annual"] = "monthly"
    payment_method:  str  # Stripe payment method ID

class Subscription(BaseModel):
    """Full subscription object."""
    id:                  str
    company_id:          str
    plan:                PlanType
    status:              SubscriptionStatus
    billing_cycle:       Literal["monthly", "annual"]
    price:               float
    stripe_subscription_id: Optional[str] = None
    current_period_start: datetime
    current_period_end:   datetime
    cancel_at_period_end: bool = False
    created_at:           datetime

class Invoice(BaseModel):
    """Invoice record."""
    id:          str
    company_id:  str
    amount:      float
    currency:    str = "usd"
    status:      Literal["paid", "pending", "failed"]
    description: str
    stripe_invoice_id: Optional[str] = None
    issued_at:   datetime
    paid_at:     Optional[datetime] = None
    pdf_url:     Optional[str] = None

class BillingDashboard(BaseModel):
    """Full billing overview for admin."""
    company_id:       str
    current_plan:     PlanDetails
    subscription:     Optional[Subscription] = None
    invoices:         List[Invoice] = []
    next_billing_date: Optional[datetime] = None
    monthly_spend:    float = 0.0

# ============================================================
# PHASE 22 — COMPANY-WIDE DATA LAYER
# ============================================================

class CompanyRole(BaseModel):
    """A role/job saved by the company."""
    id:          str
    company_id:  str
    created_by:  str  # user_id
    title:       str
    description: str
    location:    str
    skills:      List[str] = []
    boolean:     Optional[str] = None
    is_active:   bool = True
    created_at:  datetime
    updated_at:  datetime

class CompanyCandidate(BaseModel):
    """A candidate saved at company level."""
    id:           str
    company_id:   str
    added_by:     str  # user_id
    name:         str
    role:         str
    tier:         Literal["gold", "silver", "bronze"]
    match_score:  int
    adaptability: int
    focus_penalty: int
    ai_analysis:  str
    silent_skill: Optional[str] = None
    linkedin_url: Optional[str] = None
    photo:        Optional[str] = None
    notes:        str = ""
    shortlisted:  bool = False
    job_id:       Optional[str] = None
    created_at:   datetime

class CompanyShortlist(BaseModel):
    """Company-wide shortlist."""
    company_id:  str
    candidates:  List[CompanyCandidate]
    total:       int
    created_by:  Optional[str] = None

# ============================================================
# PHASE 22 — ANALYTICS DASHBOARD
# ============================================================

class UsageMetric(BaseModel):
    """Single usage data point."""
    date:   str
    value:  int
    label:  str

class TeamActivityItem(BaseModel):
    """Single team activity entry."""
    user_name:  str
    action:     str
    timestamp:  datetime
    details:    Optional[str] = None

class CompanyAnalytics(BaseModel):
    """Full company analytics for admin dashboard."""
    company_id:         str
    period:             Literal["7d", "30d", "90d"] = "30d"

    # Usage
    total_searches:     int = 0
    total_candidates:   int = 0
    total_shortlists:   int = 0
    ai_calls_used:      int = 0
    ai_calls_limit:     int = 100

    # Performance
    avg_latency_ms:     float = 0.0
    avg_match_score:    float = 0.0

    # Team
    active_users:       int = 0
    total_users:        int = 0

    # Charts
    searches_over_time: List[UsageMetric] = []
    candidates_by_tier: dict = {}

    # Activity
    recent_activity:    List[TeamActivityItem] = []

    # Cost
    estimated_cost:     float = 0.0
    cost_breakdown:     dict = {}

# ============================================================
# PHASE 22 — API RESPONSES
# ============================================================

class APIResponse(BaseModel):
    """Standard API response wrapper."""
    success:  bool
    message:  str = ""
    data:     Optional[dict] = None
    error:    Optional[str] = None

class PaginatedResponse(BaseModel):
    """Paginated list response."""
    items:   list
    total:   int
    page:    int
    limit:   int
    pages:   int