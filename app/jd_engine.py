# ============================================================
# app/jd_engine.py
# AI Talent Match Pro — Phase 32B AI Job Description Engine
# GPT-4o powered JD generation with tone + role-type customization
# Better JD = better candidate matching = $1B moat
# ============================================================

import uuid
import time
import json
import hashlib
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import httpx
import os

from app.db import JobDescriptionORM, CompanyRoleORM
from app.cost_engine import calculate_ai_cost, track_ai_call

# ============================================================
# CONFIG
# ============================================================
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "https://ai-talent-match-openai.openai.azure.com/")
AZURE_OPENAI_KEY        = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = "gpt-4o"

PROMPT_VERSION = "v32.1"
CACHE_TTL_DAYS = 30

# ============================================================
# TONE DEFINITIONS
# ============================================================
TONES = {
    "professional": {
        "label":       "Professional",
        "description": "Formal, structured, enterprise-grade",
        "voice":       "Write in a formal, precise tone suitable for enterprise companies. Use structured language that conveys authority and professionalism."
    },
    "conversational": {
        "label":       "Conversational",
        "description": "Friendly, human, approachable",
        "voice":       "Write in a warm, human tone as if speaking directly to the candidate. Be friendly, approachable, and authentic. Avoid corporate jargon."
    },
    "bold": {
        "label":       "Bold / Startup",
        "description": "Energetic, ambitious, startup culture",
        "voice":       "Write with energy and ambition. Be direct and provocative. This is for a fast-moving company that wants exceptional people who want to change the world."
    },
    "enterprise": {
        "label":       "Enterprise",
        "description": "Structured, compliance-ready, institutional",
        "voice":       "Write in a highly structured, compliance-friendly tone suitable for large enterprises. Include clear scope, hierarchy, and measurable outcomes."
    }
}

# ============================================================
# ROLE TYPE DEFINITIONS
# ============================================================
ROLE_TYPES = {
    "technical": {
        "label":    "Technical",
        "focus":    "Emphasize technical skills, stack, architecture decisions, and engineering culture. Use precise technical language.",
        "sections": ["Role Overview", "What You'll Build", "Technical Requirements", "Nice to Have", "What We Offer"]
    },
    "leadership": {
        "label":    "Leadership",
        "focus":    "Emphasize vision, impact, team leadership, and strategic thinking. Focus on outcomes over tasks.",
        "sections": ["The Opportunity", "What You'll Lead", "What We're Looking For", "What Success Looks Like", "Why Join Us"]
    },
    "creative": {
        "label":    "Creative",
        "focus":    "Emphasize creativity, brand voice, storytelling, and culture. Inspire candidates with the mission.",
        "sections": ["The Creative Brief", "What You'll Create", "Your Creative Profile", "Our Creative Culture", "Perks & Benefits"]
    },
    "sales": {
        "label":    "Sales",
        "focus":    "Emphasize targets, earnings potential, competitive drive, and growth. Use achievement-oriented language.",
        "sections": ["The Opportunity", "What You'll Own", "Your Sales Profile", "Compensation & OTE", "Why Our Team Wins"]
    }
}


# ============================================================
# STEP 2 — BUILD JD PROMPT
# ============================================================

def build_jd_prompt(
    role_title: str,
    company_name: str,
    location: str,
    skills: str,
    tone: str,
    role_type: str,
    additional_context: str = ""
) -> str:
    """
    Build a GPT-4o prompt for generating a job description.
    Combines tone + role_type for maximum precision.
    """
    tone_config      = TONES.get(tone, TONES["professional"])
    role_config      = ROLE_TYPES.get(role_type, ROLE_TYPES["technical"])
    sections         = " | ".join(role_config["sections"])

    prompt = f"""You are an expert talent brand copywriter creating a world-class job description.

Company: {company_name}
Role: {role_title}
Location: {location or "Remote / Flexible"}
Key Skills: {skills or "Not specified"}
Additional Context: {additional_context or "None"}

TONE INSTRUCTION:
{tone_config["voice"]}

ROLE TYPE FOCUS:
{role_config["focus"]}

Generate a complete job description with these EXACT sections:
{sections}

Also include:
- CULTURE: A 2-sentence paragraph about the company culture
- DEI: A 1-sentence diversity, equity & inclusion statement

RULES:
- Each section should have 4-6 bullet points or 2-3 sentences
- Be specific — use the role title and skills provided
- Do NOT use placeholder text like [Company Name] — use the actual company name
- Start with a compelling 2-sentence role hook, not a generic intro
- Total length: 400-600 words

Output ONLY the job description. No preamble, no explanation."""

    return prompt


# ============================================================
# STEP 3 — PARSE JD SECTIONS
# ============================================================

def parse_jd_sections(content: str, role_type: str) -> dict:
    """
    Parse the generated JD into structured sections.
    Returns dict with summary, responsibilities, requirements, benefits, culture, dei.
    """
    lines    = content.split('\n')
    sections = {}
    current  = None
    buffer   = []

    section_keywords = {
        "summary":        ["overview", "opportunity", "brief", "hook", "about the role"],
        "responsibilities": ["build", "lead", "create", "own", "do"],
        "requirements":   ["looking for", "require", "profile", "need", "qualifications"],
        "benefits":       ["offer", "perks", "compensation", "why", "benefits", "wins"],
        "culture":        ["culture"],
        "dei":            ["diversity", "dei", "inclusion", "equal"]
    }

    for line in lines:
        line_lower = line.lower().strip()
        matched    = False

        for section, keywords in section_keywords.items():
            if any(kw in line_lower for kw in keywords) and len(line.strip()) < 60:
                if current and buffer:
                    sections[current] = '\n'.join(buffer).strip()
                current = section
                buffer  = []
                matched = True
                break

        if not matched and line.strip():
            buffer.append(line)

    if current and buffer:
        sections[current] = '\n'.join(buffer).strip()

    # Fallback — if parsing fails, put everything in content
    if not sections:
        sections["summary"] = content[:300]

    return sections


# ============================================================
# STEP 4 — QUALITY SCORING
# ============================================================

def score_jd_quality(content: str) -> dict:
    """
    Auto-score JD quality on 0-100 scale.
    Checks length, specificity, sections, tone markers.
    """
    score = 100
    flags = []
    words = content.split()
    length = len(words)

    # Length check
    if length < 200:
        score -= 25
        flags.append("too_short")
    elif length > 800:
        score -= 10
        flags.append("too_long")

    # Generic language check
    generic = ["passionate", "team player", "fast-paced", "self-starter", "dynamic", "synergy"]
    generic_count = sum(1 for g in generic if g.lower() in content.lower())
    if generic_count > 3:
        score -= 15
        flags.append("generic_language")

    # Section check — should have multiple sections
    section_markers = ["##", "**", "Requirements", "Responsibilities", "Benefits", "Culture"]
    section_count   = sum(1 for m in section_markers if m in content)
    if section_count < 3:
        score -= 10
        flags.append("missing_sections")

    # DEI check
    if "diversity" not in content.lower() and "equal" not in content.lower():
        score -= 5
        flags.append("no_dei_statement")

    # Bullet point check
    bullets = content.count('•') + content.count('-') + content.count('*')
    if bullets < 5:
        score -= 10
        flags.append("low_structure")

    return {
        "score": max(0, score),
        "grade": "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D",
        "flags": flags,
        "word_count": length
    }


# ============================================================
# STEP 5 — MAIN GENERATE FUNCTION
# ============================================================

async def generate_job_description(
    db: Session,
    job_id: str,
    company_id: str,
    company_name: str,
    user_id: str,
    tone: str = "professional",
    role_type: str = "technical",
    additional_context: str = ""
) -> dict:
    """
    Generate an AI job description for a role.
    Uses GPT-4o, Phase 28 cost tracking, and quality scoring.
    Returns full JD with sections + metadata.
    """
    start = time.time()

    # Validate tone + role_type
    if tone not in TONES:
        tone = "professional"
    if role_type not in ROLE_TYPES:
        role_type = "technical"

    # Get role details
    job = db.query(CompanyRoleORM).filter(
        CompanyRoleORM.id == job_id,
        CompanyRoleORM.company_id == company_id,
        CompanyRoleORM.is_deleted == False
    ).first()

    if not job:
        return {"error": "Role not found"}

    # Check for cached JD
    cached = db.query(JobDescriptionORM).filter(
        JobDescriptionORM.job_id == job_id,
        JobDescriptionORM.company_id == company_id,
        JobDescriptionORM.tone == tone,
        JobDescriptionORM.role_type == role_type,
        JobDescriptionORM.is_active == True,
        JobDescriptionORM.is_deleted == False
    ).first()

    if cached and cached.updated_at > datetime.utcnow() - timedelta(days=CACHE_TTL_DAYS):
        return {
            "jd_id":             cached.id,
            "content":           cached.content,
            "summary":           cached.summary,
            "responsibilities":  cached.responsibilities,
            "requirements":      cached.requirements,
            "benefits":          cached.benefits,
            "culture":           cached.culture,
            "dei_statement":     cached.dei_statement,
            "tone":              cached.tone,
            "role_type":         cached.role_type,
            "quality_score":     cached.quality_score,
            "word_count":        cached.word_count,
            "version":           cached.version,
            "cost_usd":          0.0,
            "cached":            True,
            "model":             cached.model_used
        }

    # Build prompt
    prompt = build_jd_prompt(
        role_title=job.title,
        company_name=company_name,
        location=job.location or "",
        skills=job.skills or "",
        tone=tone,
        role_type=role_type,
        additional_context=additional_context
    )

    # Call GPT-4o
    content    = ""
    tokens_in  = 0
    tokens_out = 0

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AZURE_OPENAI_ENDPOINT}openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version=2024-02-01",
                headers={"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"},
                json={
                    "messages":   [{"role": "user", "content": prompt}],
                    "max_tokens": 800,
                    "temperature": 0.75
                },
                timeout=20.0
            )
            result     = response.json()
            content    = result["choices"][0]["message"]["content"].strip()
            tokens_in  = result.get("usage", {}).get("prompt_tokens", 0)
            tokens_out = result.get("usage", {}).get("completion_tokens", 0)
    except Exception:
        content = _fallback_jd(job.title, company_name, tone, role_type)

    latency_ms = round((time.time() - start) * 1000, 2)
    cost_usd   = calculate_ai_cost(AZURE_OPENAI_DEPLOYMENT, tokens_in, tokens_out)

    # Parse sections
    sections = parse_jd_sections(content, role_type)

    # Quality score
    quality = score_jd_quality(content)

    # Get next version number
    last_version = db.query(JobDescriptionORM).filter(
        JobDescriptionORM.job_id == job_id,
        JobDescriptionORM.company_id == company_id
    ).count()

    # Deactivate old JDs
    db.query(JobDescriptionORM).filter(
        JobDescriptionORM.job_id == job_id,
        JobDescriptionORM.company_id == company_id,
        JobDescriptionORM.is_active == True
    ).update({"is_active": False})

    # Save new JD
    jd = JobDescriptionORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        job_id=job_id,
        content=content,
        summary=sections.get("summary", "")[:500],
        responsibilities=sections.get("responsibilities", ""),
        requirements=sections.get("requirements", ""),
        benefits=sections.get("benefits", ""),
        culture=sections.get("culture", ""),
        dei_statement=sections.get("dei", ""),
        tone=tone,
        role_type=role_type,
        model_used=AZURE_OPENAI_DEPLOYMENT,
        prompt_version=PROMPT_VERSION,
        tokens_used=tokens_in + tokens_out,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        version=last_version + 1,
        is_active=True,
        quality_score=quality["score"],
        word_count=quality["word_count"],
        created_by=user_id
    )
    db.add(jd)

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
        action="ai_jd_generate"
    )

    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "jd_id":            jd.id,
        "content":          content,
        "summary":          sections.get("summary", ""),
        "responsibilities": sections.get("responsibilities", ""),
        "requirements":     sections.get("requirements", ""),
        "benefits":         sections.get("benefits", ""),
        "culture":          sections.get("culture", ""),
        "dei_statement":    sections.get("dei", ""),
        "tone":             tone,
        "tone_label":       TONES[tone]["label"],
        "role_type":        role_type,
        "role_type_label":  ROLE_TYPES[role_type]["label"],
        "quality_score":    quality["score"],
        "quality_grade":    quality["grade"],
        "quality_flags":    quality["flags"],
        "word_count":       quality["word_count"],
        "version":          last_version + 1,
        "cost_usd":         cost_usd,
        "tokens_in":        tokens_in,
        "tokens_out":       tokens_out,
        "latency_ms":       latency_ms,
        "cached":           False,
        "model":            AZURE_OPENAI_DEPLOYMENT,
        "prompt_version":   PROMPT_VERSION
    }


# ============================================================
# FALLBACK JD
# ============================================================

def _fallback_jd(
    title: str,
    company: str,
    tone: str,
    role_type: str
) -> str:
    """Generate fallback JD when API fails."""
    role_section = {
        "technical":   "What You'll Build",
        "leadership":  "What You'll Lead",
        "creative":    "What You'll Create",
        "sales":       "What You'll Own"
    }.get(role_type, "Responsibilities")

    return f"""## {title} at {company}

We are looking for an exceptional {title} to join our team at {company}. This is a rare opportunity to make a significant impact at a fast-growing company.

## {role_section}
- Drive key initiatives and deliver measurable outcomes
- Collaborate with cross-functional teams to achieve goals
- Build and maintain high-quality systems and processes
- Contribute to company strategy and growth

## What We're Looking For
- Proven experience in a similar role
- Strong communication and collaboration skills
- Ability to work in a fast-paced environment
- Passion for excellence and continuous improvement

## What We Offer
- Competitive compensation package
- Flexible working arrangements
- Career development opportunities
- Collaborative and inclusive culture

## Culture
At {company}, we believe in empowering our team to do their best work. We foster a culture of trust, transparency, and continuous learning.

We are committed to building a diverse and inclusive workplace where everyone can thrive."""


# ============================================================
# HELPERS
# ============================================================

def get_jd_for_role(
    db: Session,
    job_id: str,
    company_id: str
) -> "Optional[dict]":
    """Get the active JD for a role."""
    jd = db.query(JobDescriptionORM).filter(
        JobDescriptionORM.job_id == job_id,
        JobDescriptionORM.company_id == company_id,
        JobDescriptionORM.is_active == True,
        JobDescriptionORM.is_deleted == False
    ).first()

    if not jd:
        return None

    return {
        "jd_id":         jd.id,
        "content":       jd.content,
        "tone":          jd.tone,
        "role_type":     jd.role_type,
        "quality_score": jd.quality_score,
        "word_count":    jd.word_count,
        "version":       jd.version,
        "created_at":    jd.created_at.isoformat()
    }


def get_available_tones() -> list:
    """Return all available tones for UI dropdowns."""
    return [
        {"key": k, "label": v["label"], "description": v["description"]}
        for k, v in TONES.items()
    ]


def get_available_role_types() -> list:
    """Return all available role types for UI dropdowns."""
    return [
        {"key": k, "label": v["label"], "focus": v["focus"]}
        for k, v in ROLE_TYPES.items()
    ]