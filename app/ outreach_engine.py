# ============================================================
# app/outreach_engine.py
# AI Talent Match Pro — Phase 33 AI Outreach Engine
# GPT-4o powered personalized recruiter messages
# LinkedIn connection, InMail, Email, Follow-up, Rejection
# ============================================================

import uuid
import time
import os
from datetime import datetime
from sqlalchemy.orm import Session
import httpx

from app.db import (
    OutreachORM, CompanyCandidateORM,
    AINarrativeORM, CompanyRoleORM
)
from app.cost_engine import calculate_ai_cost, track_ai_call

# ============================================================
# CONFIG
# ============================================================
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "https://ai-talent-match-openai.openai.azure.com/")
AZURE_OPENAI_KEY        = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = "gpt-4o"

PROMPT_VERSION = "v33.1"

# ============================================================
# MESSAGE TYPES + LIMITS
# ============================================================
MESSAGE_TYPES = {
    "linkedin_connection": {
        "label":       "LinkedIn Connection Request",
        "char_limit":  300,
        "channel":     "linkedin",
        "description": "Short, warm connection request"
    },
    "linkedin_inmail": {
        "label":       "LinkedIn InMail",
        "char_limit":  1000,
        "channel":     "linkedin",
        "description": "Full InMail with context and ask"
    },
    "email": {
        "label":       "Email Outreach",
        "char_limit":  2000,
        "channel":     "email",
        "description": "Full email with subject line"
    },
    "followup": {
        "label":       "Follow-up Message",
        "char_limit":  500,
        "channel":     "linkedin",
        "description": "Gentle follow-up after no response"
    },
    "rejection": {
        "label":       "Kind Rejection",
        "char_limit":  500,
        "channel":     "email",
        "description": "Warm, respectful rejection message"
    }
}

# ============================================================
# TONE DEFINITIONS
# ============================================================
OUTREACH_TONES = {
    "warm":         "Write in a warm, human, genuine tone. Feel like a real person, not a recruiter bot.",
    "professional": "Write in a professional, respectful tone. Formal but approachable.",
    "bold":         "Write with energy and confidence. Direct, exciting, startup-style.",
    "concise":      "Write as short as possible. Every word counts. No fluff."
}


# ============================================================
# STEP 1 — BUILD OUTREACH PROMPT
# ============================================================

def build_outreach_prompt(
    candidate_name: str,
    role_title: str,
    company_name: str,
    tier: str,
    match_score: float,
    silent_skill: str,
    ai_analysis: str,
    narrative: str,
    message_type: str,
    tone: str,
    recruiter_name: str = "the recruiter"
) -> str:
    """
    Build a GPT-4o prompt for generating personalized outreach.
    Uses candidate narrative + AI analysis for deep personalization.
    """
    type_config  = MESSAGE_TYPES.get(message_type, MESSAGE_TYPES["linkedin_connection"])
    tone_config  = OUTREACH_TONES.get(tone, OUTREACH_TONES["warm"])
    char_limit   = type_config["char_limit"]
    type_label   = type_config["label"]

    # Tier-specific urgency
    tier_context = {
        "gold":   "This is a top-tier candidate — treat them like a rare find.",
        "silver": "This is a strong candidate worth engaging seriously.",
        "bronze": "This is an interesting adjacent candidate — be exploratory."
    }.get(tier, "")

    prompts = {
        "linkedin_connection": f"""You are an expert recruiter writing a LinkedIn connection request.

Candidate: {candidate_name}
Role: {role_title} at {company_name}
Match Score: {match_score}/100 | Tier: {tier.upper()}
Silent Skill: {silent_skill}
AI Analysis: {ai_analysis[:200]}
Narrative: {narrative[:300] if narrative else 'Not available'}
{tier_context}

TONE: {tone_config}

Write a LinkedIn connection request note. Rules:
- MAX {char_limit} characters (hard limit)
- Reference something specific about {candidate_name}
- Mention the role naturally — don't make it feel like a job blast
- End with a soft, no-pressure ask
- Do NOT start with "Hi" or "Dear"
- Output ONLY the message, nothing else""",

        "linkedin_inmail": f"""You are an expert recruiter writing a LinkedIn InMail.

Candidate: {candidate_name}
Role: {role_title} at {company_name}
Match Score: {match_score}/100 | Tier: {tier.upper()}
Silent Skill: {silent_skill}
AI Analysis: {ai_analysis[:300]}
Narrative: {narrative[:400] if narrative else 'Not available'}
{tier_context}

TONE: {tone_config}

Write a LinkedIn InMail. Rules:
- Subject line first, then message
- MAX {char_limit} characters total
- Open with something specific to {candidate_name}
- Explain why THIS role at THIS company is right for them
- Reference their specific skills/trajectory
- Clear call to action — 15-minute call
- Format: SUBJECT: [subject]\n\n[message body]
- Output ONLY the message, nothing else""",

        "email": f"""You are an expert recruiter writing a personalized outreach email.

Candidate: {candidate_name}
Role: {role_title} at {company_name}
Match Score: {match_score}/100 | Tier: {tier.upper()}
Silent Skill: {silent_skill}
AI Analysis: {ai_analysis[:300]}
Narrative: {narrative[:400] if narrative else 'Not available'}
Recruiter: {recruiter_name}
{tier_context}

TONE: {tone_config}

Write a personalized outreach email. Rules:
- Subject line first, then email body
- Warm, human opening — reference something specific
- 3-4 short paragraphs max
- Why this role is perfect for {candidate_name}
- Clear next step — reply or book a call
- Sign off with recruiter name
- Format: SUBJECT: [subject]\n\n[email body]
- Output ONLY the email, nothing else""",

        "followup": f"""You are an expert recruiter writing a follow-up message.

Candidate: {candidate_name}
Role: {role_title} at {company_name}
{tier_context}

TONE: {tone_config}

Write a gentle follow-up. Rules:
- MAX {char_limit} characters
- No guilt, no pressure
- Acknowledge they're busy
- Re-state the opportunity in one sentence
- Easy yes/no ask
- Output ONLY the message, nothing else""",

        "rejection": f"""You are an expert recruiter writing a kind rejection message.

Candidate: {candidate_name}
Role: {role_title} at {company_name}

TONE: Warm, genuine, respectful. Leave them feeling good about the company.

Write a rejection message. Rules:
- MAX {char_limit} characters
- Thank them genuinely
- Be honest but kind — not a fit for THIS role
- Leave door open for future
- Never say "we'll keep your resume on file" (feels fake)
- Output ONLY the message, nothing else"""
    }

    return prompts.get(message_type, prompts["linkedin_connection"])


# ============================================================
# STEP 2 — QUALITY SCORING
# ============================================================

def score_outreach_quality(message: str, message_type: str) -> float:
    """Score outreach message quality 0-100."""
    score = 100
    char_limit = MESSAGE_TYPES.get(message_type, {}).get("char_limit", 300)

    # Length check
    if len(message) > char_limit:
        score -= 20
    if len(message) < 50:
        score -= 30

    # Generic language check
    generic = ["I came across your profile", "I hope this message finds you well",
               "We're looking for talented", "opportunity of a lifetime", "competitive salary"]
    for phrase in generic:
        if phrase.lower() in message.lower():
            score -= 10

    # Personalization check — does it mention specifics?
    if not any(word in message for word in ["your", "you've", "you're", "your background"]):
        score -= 15

    return max(0, min(100, score))


# ============================================================
# STEP 3 — MAIN GENERATE FUNCTION
# ============================================================

async def generate_outreach(
    db: Session,
    candidate_id: str,
    company_id: str,
    user_id: str,
    message_type: str = "linkedin_connection",
    tone: str = "warm",
    recruiter_name: str = "",
    project_id: str = None
) -> dict:
    """
    Generate AI-powered outreach message for a candidate.
    Pulls narrative from Phase 29 for deep personalization.
    Returns message + metadata + cost breakdown.
    """
    start = time.time()

    # Validate message type
    if message_type not in MESSAGE_TYPES:
        return {"error": f"Invalid message type. Choose: {list(MESSAGE_TYPES.keys())}"}

    # Get candidate
    candidate = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.id == candidate_id,
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.is_deleted == False
    ).first()

    if not candidate:
        return {"error": "Candidate not found"}

    # Get role title
    role_title = candidate.role or "the role"
    if candidate.job_id:
        job = db.query(CompanyRoleORM).filter(CompanyRoleORM.id == candidate.job_id).first()
        if job:
            role_title = job.title

    # Get narrative from Phase 29 (if available)
    narrative = ""
    cached_narrative = db.query(AINarrativeORM).filter(
        AINarrativeORM.candidate_id == candidate_id,
        AINarrativeORM.company_id == company_id,
        AINarrativeORM.is_deleted == False
    ).order_by(AINarrativeORM.created_at.desc()).first()

    if cached_narrative:
        narrative = cached_narrative.narrative

    # Build prompt
    prompt = build_outreach_prompt(
        candidate_name=candidate.name,
        role_title=role_title,
        company_name="your company",  # will be overridden by caller
        tier=candidate.tier,
        match_score=candidate.match_score,
        silent_skill=candidate.silent_skill or "strategic thinking",
        ai_analysis=candidate.ai_analysis or "",
        narrative=narrative,
        message_type=message_type,
        tone=tone,
        recruiter_name=recruiter_name
    )

    # Call GPT-4o
    message    = ""
    subject    = ""
    tokens_in  = 0
    tokens_out = 0

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AZURE_OPENAI_ENDPOINT}openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version=2024-02-01",
                headers={"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"},
                json={
                    "messages":    [{"role": "user", "content": prompt}],
                    "max_tokens":  600,
                    "temperature": 0.75
                },
                timeout=15.0
            )
            result     = response.json()
            content    = result["choices"][0]["message"]["content"].strip()
            tokens_in  = result.get("usage", {}).get("prompt_tokens", 0)
            tokens_out = result.get("usage", {}).get("completion_tokens", 0)

            # Extract subject if email/inmail
            if message_type in ("email", "linkedin_inmail") and "SUBJECT:" in content:
                lines   = content.split("\n")
                subject = lines[0].replace("SUBJECT:", "").strip()
                message = "\n".join(lines[2:]).strip()
            else:
                message = content

    except Exception:
        message = _fallback_outreach(candidate.name, role_title, message_type, tone)

    latency_ms = round((time.time() - start) * 1000, 2)
    cost_usd   = calculate_ai_cost(AZURE_OPENAI_DEPLOYMENT, tokens_in, tokens_out)
    quality    = score_outreach_quality(message, message_type)
    char_count = len(message)

    # Save to OutreachORM
    outreach = OutreachORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        candidate_id=candidate_id,
        created_by=user_id,
        project_id=project_id,
        message_type=message_type,
        channel=MESSAGE_TYPES[message_type]["channel"],
        subject=subject,
        content=message,
        char_count=char_count,
        tone=tone,
        personalization_score=quality,
        model_used=AZURE_OPENAI_DEPLOYMENT,
        prompt_version=PROMPT_VERSION,
        tokens_used=tokens_in + tokens_out,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        quality_score=quality,
        sent=False
    )
    db.add(outreach)

    # Track cost (Phase 28)
    track_ai_call(
        db=db,
        company_id=company_id,
        user_id=user_id,
        model_name=AZURE_OPENAI_DEPLOYMENT,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        cache_hit=False,
        action="ai_outreach"
    )

    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "outreach_id":      outreach.id,
        "message":          message,
        "subject":          subject,
        "message_type":     message_type,
        "type_label":       MESSAGE_TYPES[message_type]["label"],
        "channel":          MESSAGE_TYPES[message_type]["channel"],
        "char_count":       char_count,
        "char_limit":       MESSAGE_TYPES[message_type]["char_limit"],
        "tone":             tone,
        "quality_score":    quality,
        "personalization":  quality,
        "cost_usd":         cost_usd,
        "tokens_in":        tokens_in,
        "tokens_out":       tokens_out,
        "latency_ms":       latency_ms,
        "prompt_version":   PROMPT_VERSION,
        "candidate_name":   candidate.name,
        "candidate_tier":   candidate.tier
    }


# ============================================================
# STEP 4 — BATCH OUTREACH
# Generate outreach for all shortlisted candidates
# ============================================================

async def generate_batch_outreach(
    db: Session,
    company_id: str,
    user_id: str,
    message_type: str = "linkedin_connection",
    tone: str = "warm",
    project_id: str = None
) -> dict:
    """
    Generate outreach messages for all shortlisted candidates.
    Cost-optimized batch generation.
    """
    candidates = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.shortlisted == True,
        CompanyCandidateORM.is_deleted == False
    ).all()

    results     = []
    total_cost  = 0.0
    generated   = 0
    failed      = 0

    for candidate in candidates:
        result = await generate_outreach(
            db=db,
            candidate_id=candidate.id,
            company_id=company_id,
            user_id=user_id,
            message_type=message_type,
            tone=tone,
            project_id=project_id
        )
        if "error" not in result:
            results.append({
                "candidate_id":   candidate.id,
                "candidate_name": candidate.name,
                "tier":           candidate.tier,
                **result
            })
            total_cost += result.get("cost_usd", 0)
            generated  += 1
        else:
            failed += 1

    return {
        "total":      len(candidates),
        "generated":  generated,
        "failed":     failed,
        "total_cost": round(total_cost, 6),
        "results":    results
    }


# ============================================================
# STEP 5 — MARK AS SENT
# ============================================================

def mark_outreach_sent(
    db: Session,
    outreach_id: str,
    company_id: str,
    sent_via: str = "manual"
) -> bool:
    """Mark an outreach message as sent."""
    outreach = db.query(OutreachORM).filter(
        OutreachORM.id == outreach_id,
        OutreachORM.company_id == company_id
    ).first()

    if not outreach:
        return False

    outreach.sent     = True
    outreach.sent_at  = datetime.utcnow()
    outreach.sent_via = sent_via

    try:
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False


# ============================================================
# STEP 6 — GET OUTREACH STATS
# ============================================================

def get_outreach_stats(db: Session, company_id: str) -> dict:
    """Get outreach statistics for the dashboard."""
    messages = db.query(OutreachORM).filter(
        OutreachORM.company_id == company_id,
        OutreachORM.is_deleted == False
    ).all()

    total      = len(messages)
    sent       = sum(1 for m in messages if m.sent)
    responded  = sum(1 for m in messages if m.responded)
    total_cost = sum(m.cost_usd or 0 for m in messages)

    by_type = {}
    for msg_type in MESSAGE_TYPES:
        type_msgs = [m for m in messages if m.message_type == msg_type]
        by_type[msg_type] = {
            "total":     len(type_msgs),
            "sent":      sum(1 for m in type_msgs if m.sent),
            "responded": sum(1 for m in type_msgs if m.responded)
        }

    return {
        "total":          total,
        "sent":           sent,
        "unsent":         total - sent,
        "responded":      responded,
        "response_rate":  round(responded / max(sent, 1) * 100, 1),
        "total_cost":     round(total_cost, 4),
        "by_type":        by_type
    }


# ============================================================
# FALLBACK OUTREACH
# ============================================================

def _fallback_outreach(name: str, role: str, message_type: str, tone: str) -> str:
    """Fallback message when API fails."""
    fallbacks = {
        "linkedin_connection": f"Hi {name}, I came across your profile and was impressed by your background. I'm working on an exciting {role} opportunity and think you could be a great fit. Would love to connect and share more!",
        "linkedin_inmail":     f"SUBJECT: {role} Opportunity — Thought of You\n\nHi {name},\n\nI've been following your career and think you'd be an excellent fit for a {role} role I'm working on. The work is meaningful, the team is exceptional, and the timing feels right.\n\nWould you be open to a quick 15-minute call this week?\n\nLooking forward to connecting.",
        "email":               f"SUBJECT: {role} — I Think You'd Love This\n\nHi {name},\n\nI hope this finds you well. I'm reaching out because your background caught my attention, and I believe you'd be an exceptional fit for a {role} opportunity I'm currently working on.\n\nI'd love to share more details. Would you be open to a brief call?\n\nBest regards",
        "followup":            f"Hi {name} — just wanted to follow up on my previous message about the {role} opportunity. Completely understand if the timing isn't right, but wanted to make sure it didn't get lost. Happy to chat whenever works for you!",
        "rejection":           f"Hi {name}, thank you so much for your interest and time. After careful consideration, we've decided to move forward with other candidates for this particular role. I genuinely appreciate you considering us, and I hope our paths cross again in the future."
    }
    return fallbacks.get(message_type, fallbacks["linkedin_connection"])


# ============================================================
# HELPERS
# ============================================================

def get_message_types() -> list:
    """Return all available message types for UI dropdowns."""
    return [
        {"key": k, "label": v["label"], "char_limit": v["char_limit"],
         "channel": v["channel"], "description": v["description"]}
        for k, v in MESSAGE_TYPES.items()
    ]


def get_outreach_tones() -> list:
    """Return all available tones for UI dropdowns."""
    return [
        {"key": k, "description": v}
        for k, v in OUTREACH_TONES.items()
    ]