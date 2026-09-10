# ============================================================
# app/narrative_engine.py
# AI Talent Match Pro — Phase 29 Narrative Intelligence Engine
# Transforms raw candidate data into human-quality storytelling
# This is the phase that makes the platform feel alive
# ============================================================

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid
import hashlib
import httpx
import os

from app.db import (
    AINarrativeORM, CompanyCandidateORM,
    CompanyRoleORM, UsageLogORM
)
from app.cost_engine import (
    calculate_ai_cost, select_model_for_tier,
    generate_cache_key, track_ai_call
)

# ============================================================
# AZURE OPENAI CONFIG
# ============================================================
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "https://ai-talent-match-openai.openai.azure.com/")
AZURE_OPENAI_KEY        = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# ============================================================
# NARRATIVE TYPES
# ============================================================
NARRATIVE_TYPES = [
    "summary",      # Executive summary
    "strengths",    # Key strengths
    "risks",        # Potential concerns
    "culture_fit",  # Cultural alignment
    "story_arc",    # Career trajectory
    "pitch",        # How to pitch this candidate
    "full"          # All of the above
]

# ============================================================
# PROMPT VERSION
# ============================================================
PROMPT_VERSION    = "v29.1"
NARRATIVE_VERSION = "v29.1"
CACHE_TTL_HOURS   = 168  # 7 days


# ============================================================
# STEP 2 — NARRATIVE PROMPT ENGINE
# Reusable prompt templates per narrative type
# ============================================================

def build_narrative_prompt(
    candidate_name: str,
    role: str,
    tier: str,
    match_score: float,
    adaptability: float,
    focus_penalty: float,
    silent_skill: str,
    ai_analysis: str,
    job_description: str,
    narrative_type: str
) -> str:
    """
    Build a narrative prompt based on candidate data and type.
    """
    base_context = f"""
Candidate: {candidate_name}
Role Applied For: {role}
Match Score: {match_score}/100
Adaptability Score: {adaptability}/100
Focus Penalty: {focus_penalty}/100
Silent Skill: {silent_skill}
AI Analysis: {ai_analysis}
Job Description: {job_description[:500] if job_description else 'Not provided'}
Candidate Tier: {tier.upper()} {'🥇' if tier == 'gold' else '🥈' if tier == 'silver' else '🥉'}
""".strip()

    prompts = {
        "summary": f"""You are an expert talent advisor writing for a senior recruiter.
{base_context}

Write a 2-3 sentence executive summary of this candidate.
- Start with "{candidate_name}'s trajectory..."
- Be specific, warm, and professional
- Highlight what makes them unique
- Output only the summary, nothing else.""",

        "strengths": f"""You are an expert talent advisor.
{base_context}

List exactly 3 key strengths of this candidate for the {role} role.
Format as:
1. [Strength]: [One sentence explanation]
2. [Strength]: [One sentence explanation]
3. [Strength]: [One sentence explanation]
Output only the numbered list, nothing else.""",

        "risks": f"""You are an expert talent advisor providing balanced counsel.
{base_context}

List 2 potential risks or gaps for this candidate in the {role} role.
Be honest but constructive. Format as:
1. [Risk]: [One sentence explanation and mitigation]
2. [Risk]: [One sentence explanation and mitigation]
Output only the numbered list, nothing else.""",

        "culture_fit": f"""You are an expert talent advisor assessing cultural alignment.
{base_context}

Write 2 sentences about this candidate's likely cultural fit.
- Consider their adaptability score of {adaptability}/100
- Reference their silent skill: {silent_skill}
- Be insightful and specific
Output only the culture fit assessment, nothing else.""",

        "story_arc": f"""You are an expert talent advisor who specializes in career narratives.
{base_context}

Write 2-3 sentences about this candidate's career trajectory and where they are heading.
- Focus on growth patterns and future potential
- Use language like "Their pattern suggests..." or "The arc here is..."
- Be forward-looking and inspiring
Output only the story arc, nothing else.""",

        "pitch": f"""You are an expert talent advisor helping a recruiter pitch a candidate to a hiring manager.
{base_context}

Write a 3-4 sentence pitch for this candidate.
- Lead with their strongest differentiator
- Address potential objections proactively
- Close with why now is the right time to meet them
Output only the pitch, nothing else.""",

        "full": f"""You are an expert talent advisor creating a comprehensive candidate brief.
{base_context}

Generate a complete candidate narrative with these exact sections:

SUMMARY:
[2-3 sentence executive summary starting with "{candidate_name}'s trajectory..."]

STRENGTHS:
1. [Strength]: [Explanation]
2. [Strength]: [Explanation]
3. [Strength]: [Explanation]

RISKS:
1. [Risk]: [Explanation + mitigation]
2. [Risk]: [Explanation + mitigation]

CULTURE FIT:
[2 sentences on cultural alignment]

STORY ARC:
[2 sentences on career trajectory]

PITCH:
[3 sentences on how to pitch to hiring manager]

Output only these sections with their headers, nothing else."""
    }

    return prompts.get(narrative_type, prompts["summary"])


# ============================================================
# STEP 5 — MAIN NARRATIVE GENERATION
# ============================================================

async def generate_narrative(
    db: Session,
    candidate_id: str,
    company_id: str,
    user_id: str,
    narrative_type: str = "full"
) -> dict:
    """
    Generate AI narrative for a candidate.
    Uses Phase 28 model tiering + caching.
    Stores result in AINarrativeORM.

    Returns: narrative dict with cost breakdown
    """
    import time

    # Get candidate data
    candidate = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.id == candidate_id,
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.is_deleted == False
    ).first()

    if not candidate:
        return {"error": "Candidate not found"}

    # Get job description if available
    job_description = ""
    if candidate.job_id:
        job = db.query(CompanyRoleORM).filter(
            CompanyRoleORM.id == candidate.job_id
        ).first()
        if job:
            job_description = job.description or ""

    # Step 3 — Model tiering
    model = select_model_for_tier(candidate.tier, task="narrative")

    # Step 4 — Check cache
    cache_key = generate_cache_key(
        f"{candidate.name}|{candidate.ai_analysis}",
        f"{job_description}|{narrative_type}",
        f"{model}|{PROMPT_VERSION}"
    )

    cached = db.query(AINarrativeORM).filter(
        AINarrativeORM.candidate_id == candidate_id,
        AINarrativeORM.company_id == company_id,
        AINarrativeORM.model_version == f"{model}-{PROMPT_VERSION}"
    ).first()

    if cached and cached.expires_at and cached.expires_at > datetime.utcnow():
        return {
            "narrative":    cached.narrative,
            "cached":       True,
            "cache_hit":    True,
            "model":        model,
            "cost_usd":     0.0,
            "latency_ms":   0,
            "tone":         cached.tone,
            "sentiment":    cached.sentiment,
            "rec_strength": cached.recommendation_strength,
            "narrative_version": NARRATIVE_VERSION
        }

    # Build prompt
    prompt = build_narrative_prompt(
        candidate_name=candidate.name,
        role=candidate.role or "the role",
        tier=candidate.tier,
        match_score=candidate.match_score,
        adaptability=candidate.adaptability or 0,
        focus_penalty=candidate.focus_penalty or 0,
        silent_skill=candidate.silent_skill or "adaptive thinking",
        ai_analysis=candidate.ai_analysis or "",
        job_description=job_description,
        narrative_type=narrative_type
    )

    # Call Azure OpenAI
    start      = time.time()
    narrative  = ""
    tokens_in  = 0
    tokens_out = 0

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AZURE_OPENAI_ENDPOINT}openai/deployments/{model}/chat/completions?api-version=2024-02-01",
                headers={"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"},
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500 if narrative_type == "full" else 200,
                    "temperature": 0.7
                },
                timeout=15.0
            )
            result     = response.json()
            narrative  = result["choices"][0]["message"]["content"].strip()
            tokens_in  = result.get("usage", {}).get("prompt_tokens", 0)
            tokens_out = result.get("usage", {}).get("completion_tokens", 0)
    except Exception:
        # Fallback narrative
        narrative = _fallback_narrative(candidate, narrative_type)

    latency_ms = round((time.time() - start) * 1000, 2)
    cost_usd   = calculate_ai_cost(model, tokens_in, tokens_out)

    # Step 9 — Quality scoring
    quality = _score_narrative_quality(narrative)

    # Step 1 — Determine tone + sentiment
    tone         = "warm"         if (candidate.adaptability or 0) > 80 else "professional"
    sentiment    = "positive"     if candidate.match_score > 85 else "neutral"
    rec_strength = round(candidate.match_score / 100, 2)

    # Store in AINarrativeORM
    record = AINarrativeORM(
        id=str(uuid.uuid4()),
        candidate_id=candidate_id,
        company_id=company_id,
        narrative=narrative,
        model_version=f"{model}-{PROMPT_VERSION}",
        tokens_used=tokens_in + tokens_out,
        latency_ms=latency_ms,
        tone=tone,
        sentiment=sentiment,
        recommendation_strength=rec_strength,
        expires_at=datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS)
    )
    db.add(record)

    # Track cost (Phase 28)
    track_ai_call(
        db=db,
        company_id=company_id,
        user_id=user_id,
        model_name=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        cache_hit=False,
        action="ai_narrative"
    )

    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "narrative":         narrative,
        "cached":            False,
        "cache_hit":         False,
        "model":             model,
        "tokens_in":         tokens_in,
        "tokens_out":        tokens_out,
        "cost_usd":          cost_usd,
        "latency_ms":        latency_ms,
        "tone":              tone,
        "sentiment":         sentiment,
        "rec_strength":      rec_strength,
        "quality_score":     quality["score"],
        "quality_flags":     quality["flags"],
        "narrative_version": NARRATIVE_VERSION,
        "prompt_version":    PROMPT_VERSION
    }


# ============================================================
# STEP 6 — BATCH NARRATIVE GENERATION
# Generate narratives for all shortlisted candidates at once
# ============================================================

async def generate_batch_narratives(
    db: Session,
    company_id: str,
    user_id: str,
    narrative_type: str = "summary"
) -> dict:
    """
    Generate narratives for all shortlisted candidates.
    Cost-optimized: uses cheap model + caching.
    """
    candidates = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.shortlisted == True,
        CompanyCandidateORM.is_deleted == False
    ).all()

    results      = []
    total_cost   = 0.0
    cache_hits   = 0
    generated    = 0

    for candidate in candidates:
        result = await generate_narrative(
            db=db,
            candidate_id=candidate.id,
            company_id=company_id,
            user_id=user_id,
            narrative_type=narrative_type
        )
        if "error" not in result:
            results.append({
                "candidate_id":   candidate.id,
                "candidate_name": candidate.name,
                "tier":           candidate.tier,
                **result
            })
            total_cost += result.get("cost_usd", 0)
            if result.get("cache_hit"):
                cache_hits += 1
            else:
                generated += 1

    return {
        "total":       len(results),
        "generated":   generated,
        "cache_hits":  cache_hits,
        "total_cost":  round(total_cost, 6),
        "results":     results
    }


# ============================================================
# STEP 7 — NARRATIVE INSIGHTS
# Aggregate insights across all candidates
# ============================================================

def get_narrative_insights(db: Session, company_id: str) -> dict:
    """
    Aggregate narrative-derived insights across all candidates.
    Powers the AI Insights Dashboard.
    """
    narratives = db.query(AINarrativeORM).filter(
        AINarrativeORM.company_id == company_id,
        AINarrativeORM.is_deleted == False
    ).all()

    if not narratives:
        return {"total_narratives": 0}

    total          = len(narratives)
    positive       = sum(1 for n in narratives if n.sentiment == "positive")
    warm_tone      = sum(1 for n in narratives if n.tone == "warm")
    avg_rec        = round(sum(n.recommendation_strength or 0 for n in narratives) / total, 2)
    avg_tokens     = round(sum(n.tokens_used or 0 for n in narratives) / total, 0)
    total_cost     = sum(0.000002 * (n.tokens_used or 0) for n in narratives)

    return {
        "total_narratives":     total,
        "positive_sentiment":   positive,
        "positive_pct":         round(positive / total * 100, 1),
        "warm_tone_pct":        round(warm_tone / total * 100, 1),
        "avg_rec_strength":     avg_rec,
        "avg_tokens_per_narrative": int(avg_tokens),
        "total_narrative_cost": round(total_cost, 4)
    }


# ============================================================
# STEP 9 — NARRATIVE QUALITY SCORING
# ============================================================

def _score_narrative_quality(narrative: str) -> dict:
    """
    Score narrative quality automatically.
    Checks clarity, coherence, specificity, usefulness.
    """
    score  = 100
    flags  = []
    words  = narrative.split()
    length = len(words)

    # Length check
    if length < 20:
        score -= 20
        flags.append("too_short")
    elif length > 300:
        score -= 10
        flags.append("too_long")

    # Generic language check
    generic_phrases = ["good candidate", "strong background", "relevant experience", "team player"]
    for phrase in generic_phrases:
        if phrase.lower() in narrative.lower():
            score -= 10
            flags.append("generic_language")
            break

    # Hallucination risk check (specific numbers without context)
    import re
    numbers = re.findall(r'\b\d{4}\b', narrative)  # years
    if len(numbers) > 3:
        score -= 15
        flags.append("hallucination_risk")

    # Specificity check
    specific_words = ["trajectory", "pattern", "suggests", "signals", "demonstrates"]
    has_specific   = any(w in narrative.lower() for w in specific_words)
    if not has_specific:
        score -= 10
        flags.append("low_specificity")

    return {
        "score": max(0, score),
        "flags": flags,
        "grade": "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"
    }


# ============================================================
# FALLBACK NARRATIVE
# ============================================================

def _fallback_narrative(candidate, narrative_type: str) -> str:
    """Generate fallback narrative when API fails."""
    name        = candidate.name
    score       = candidate.match_score
    adaptability = candidate.adaptability or 0
    role        = candidate.role or "this role"
    skill       = candidate.silent_skill or "adaptive thinking"

    fallbacks = {
        "summary":    f"{name}'s trajectory suggests strong growth potential in {role}. Their match score of {score}/100 combined with an adaptability of {adaptability}/100 signals cross-functional leadership capability.",
        "strengths":  f"1. Adaptability: Scores {adaptability}/100, demonstrating strong capacity for change.\n2. Role Fit: {score}/100 match indicates solid alignment.\n3. Silent Skill: {skill} sets them apart from comparable candidates.",
        "risks":      f"1. Incomplete data: Limited signals available — recommend deeper interview.\n2. Score gap: At {score}/100, some role requirements may need development.",
        "culture_fit": f"{name}'s adaptability score of {adaptability}/100 suggests they thrive in dynamic environments. Their silent skill of {skill} indicates strong interpersonal awareness.",
        "story_arc":  f"The arc here is one of steady, deliberate growth. {name}'s pattern suggests they are building toward senior leadership in {role}.",
        "pitch":      f"{name} brings a {score}/100 match to {role} with standout {skill}. Their adaptability score of {adaptability}/100 means they ramp fast and contribute immediately. This is the candidate worth a 30-minute call.",
        "full":       f"SUMMARY:\n{name}'s trajectory suggests strong potential in {role}.\n\nSTRENGTHS:\n1. Role Fit: {score}/100\n2. Adaptability: {adaptability}/100\n3. Silent Skill: {skill}\n\nRISKS:\n1. Limited data points available\n2. Recommend deeper screening\n\nCULTURE FIT:\nStrong adaptability suggests collaborative fit.\n\nSTORY ARC:\nBuilding toward senior leadership.\n\nPITCH:\nHigh-potential candidate worth immediate outreach."
    }

    return fallbacks.get(narrative_type, fallbacks["summary"])