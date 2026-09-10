"""
============================================================
PHASE 34 — AI INTERVIEW QUESTIONS ENGINE
Generates role-specific, candidate-tailored interview
questions using GPT-4o. Scored by category, difficulty,
and relevance to tier.
============================================================
"""

import os
import json
import uuid
import time
import logging
from datetime import datetime
from typing import Optional

from openai import AzureOpenAI
from sqlalchemy.orm import Session

from app.db import (
    InterviewQuestionSetORM,
    CompanyCandidateORM,
    CompanyRoleORM,
    CompanyORM,
    UsageLogORM,
)

logger = logging.getLogger(__name__)
# 
# ── Azure OpenAI client ──────────────────────────────────
AZURE_KEY = os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY","")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT","")
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT","gpt-4o")
try:
    client = AzureOpenAI(api_key=AZURE_KEY, api_version="2024-02-01", azure_endpoint=AZURE_ENDPOINT) if AZURE_KEY else None
except Exception:
    client = None

CATEGORIES = [
    "Technical Skills",
    "Leadership & Management",
    "Culture & Values",
    "Problem Solving",
    "Role-Specific",
    "Career Trajectory",
    "Situational",
]

# ── Difficulty levels ────────────────────────────────────
DIFFICULTIES = ["Starter", "Core", "Deep Dive", "Challenge"]

# ── Tier → question depth ───────────────────────────────
TIER_DEPTH = {
    "gold":   {"count": 12, "challenge_pct": 0.3},
    "silver": {"count": 10, "challenge_pct": 0.2},
    "bronze": {"count": 8,  "challenge_pct": 0.1},
}


# ============================================================
# 34.1 — BUILD PROMPT
# ============================================================
def build_interview_prompt(
    candidate_name: str,
    candidate_role: str,
    candidate_tier: str,
    candidate_score: float,
    candidate_analysis: str,
    job_title: str,
    job_description: str,
    job_skills: str,
) -> str:
    depth = TIER_DEPTH.get(candidate_tier, TIER_DEPTH["bronze"])
    count = depth["count"]
    challenge_pct = depth["challenge_pct"]
    challenge_count = max(1, round(count * challenge_pct))

    return f"""You are an expert technical recruiter generating a precise, tailored interview question set.

CANDIDATE PROFILE:
- Name: {candidate_name}
- Current Role: {candidate_role}
- Match Tier: {candidate_tier.upper()} ({candidate_score:.0f}% match)
- AI Analysis: {candidate_analysis[:400] if candidate_analysis else 'Not available'}

ROLE BEING HIRED FOR:
- Title: {job_title}
- Description: {job_description[:600] if job_description else 'Not provided'}
- Key Skills: {job_skills if job_skills else 'Not specified'}

INSTRUCTIONS:
Generate exactly {count} interview questions tailored to this specific candidate for this specific role.
Include {challenge_count} "Challenge" level questions that probe deeply.

For each question return a JSON object with these exact fields:
- "question": the full question text (clear, specific, non-generic)
- "category": one of {CATEGORIES}
- "difficulty": one of {DIFFICULTIES}
- "why": one sentence explaining why this question is relevant to THIS candidate
- "what_good_looks_like": one sentence describing an excellent answer
- "follow_up": one natural follow-up question

Return ONLY a valid JSON array of {count} question objects. No preamble, no markdown, no explanation.
Start with [ and end with ].
"""


# ============================================================
# 34.2 — GENERATE QUESTIONS VIA GPT-4o
# ============================================================
async def generate_interview_questions(
    candidate_name: str,
    candidate_role: str,
    candidate_tier: str,
    candidate_score: float,
    candidate_analysis: str,
    job_title: str,
    job_description: str,
    job_skills: str,
) -> dict:
    start = time.time()

    prompt = build_interview_prompt(
        candidate_name=candidate_name,
        candidate_role=candidate_role,
        candidate_tier=candidate_tier,
        candidate_score=candidate_score,
        candidate_analysis=candidate_analysis,
        job_title=job_title,
        job_description=job_description,
        job_skills=job_skills,
    )

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a world-class technical recruiter. "
                        "You generate precise, non-generic interview questions "
                        "tailored to specific candidates and roles. "
                        "Always return valid JSON arrays only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=3000,
        )

        latency_ms = (time.time() - start) * 1000
        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        questions = json.loads(raw)

        tokens_used  = response.usage.total_tokens if response.usage else 0
        cost_usd     = tokens_used * 0.000005  # gpt-4o pricing approx

        return {
            "ok":          True,
            "questions":   questions,
            "count":       len(questions),
            "tokens_used": tokens_used,
            "cost_usd":    cost_usd,
            "latency_ms":  round(latency_ms, 1),
            "model":       DEPLOYMENT,
            "tier":        candidate_tier,
        }

    except json.JSONDecodeError as e:
        logger.error(f"Interview questions JSON parse error: {e}")
        return {
            "ok":    False,
            "error": "Failed to parse AI response",
            "questions": _fallback_questions(candidate_tier, job_title),
            "latency_ms": round((time.time() - start) * 1000, 1),
        }
    except Exception as e:
        logger.error(f"Interview questions generation error: {e}")
        return {
            "ok":    False,
            "error": str(e),
            "questions": _fallback_questions(candidate_tier, job_title),
            "latency_ms": round((time.time() - start) * 1000, 1),
        }


# ============================================================
# 34.3 — FALLBACK QUESTIONS (if API fails)
# ============================================================
def _fallback_questions(tier: str, job_title: str) -> list:
    base = [
        {
            "question": f"Walk me through your most relevant experience for a {job_title} role.",
            "category": "Career Trajectory",
            "difficulty": "Starter",
            "why": "Establishes baseline fit and self-awareness.",
            "what_good_looks_like": "Candidate draws clear parallels between past work and this role.",
            "follow_up": "What aspect of that experience are you most proud of?",
        },
        {
            "question": "Describe a time you had to make a high-stakes decision with incomplete information.",
            "category": "Problem Solving",
            "difficulty": "Core",
            "why": "Tests judgment under ambiguity — critical for senior roles.",
            "what_good_looks_like": "Clear framework, outcome focus, lessons learned.",
            "follow_up": "How would you approach that differently today?",
        },
        {
            "question": "What does great look like in this role, 12 months in?",
            "category": "Role-Specific",
            "difficulty": "Core",
            "why": "Reveals strategic thinking and alignment with company goals.",
            "what_good_looks_like": "Specific, measurable outcomes tied to business impact.",
            "follow_up": "How would you measure your own success?",
        },
        {
            "question": "Tell me about a time you disagreed with your manager. How did you handle it?",
            "category": "Culture & Values",
            "difficulty": "Core",
            "why": "Tests psychological safety and communication maturity.",
            "what_good_looks_like": "Respectful challenge, clear resolution, positive outcome.",
            "follow_up": "What did that experience teach you about working with leadership?",
        },
        {
            "question": "What's the hardest technical or functional problem you've solved?",
            "category": "Technical Skills",
            "difficulty": "Deep Dive",
            "why": "Surfaces depth of expertise and problem-solving methodology.",
            "what_good_looks_like": "Specific problem, clear approach, measurable result.",
            "follow_up": "What would you do differently with what you know now?",
        },
        {
            "question": "How do you prioritize when everything is urgent?",
            "category": "Situational",
            "difficulty": "Core",
            "why": "Tests execution discipline and stakeholder management.",
            "what_good_looks_like": "Clear framework, ability to negotiate, focus on impact.",
            "follow_up": "Can you give me a real example of this from the last 6 months?",
        },
        {
            "question": "Where do you want to be in 3 years?",
            "category": "Career Trajectory",
            "difficulty": "Starter",
            "why": "Checks alignment between candidate ambition and role growth path.",
            "what_good_looks_like": "Realistic, growth-oriented, tied to the company's direction.",
            "follow_up": "How does this role fit into that path?",
        },
        {
            "question": "What's something you're working on improving right now?",
            "category": "Culture & Values",
            "difficulty": "Starter",
            "why": "Tests self-awareness and growth mindset.",
            "what_good_looks_like": "Genuine, specific, shows active effort.",
            "follow_up": "What does your improvement plan look like?",
        },
    ]

    depth = TIER_DEPTH.get(tier, TIER_DEPTH["bronze"])
    return base[:depth["count"]]


# ============================================================
# 34.4 — SAVE TO DATABASE
# ============================================================
def save_question_set(
    db: Session,
    company_id: str,
    candidate_id: str,
    job_id: Optional[str],
    created_by: str,
    result: dict,
    focus_areas: Optional[str] = None,
) -> InterviewQuestionSetORM:
    questions = result.get("questions", [])

    record = InterviewQuestionSetORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        candidate_id=candidate_id,
        job_id=job_id,
        created_by=created_by,
        questions_json=json.dumps(questions),
        question_count=len(questions),
        focus_areas=focus_areas,
        model_used=result.get("model", DEPLOYMENT),
        prompt_version="v34.1",
        tokens_used=result.get("tokens_used", 0),
        cost_usd=result.get("cost_usd", 0.0),
        latency_ms=result.get("latency_ms", 0.0),
        tier=result.get("tier", "bronze"),
    )

    db.add(record)

    # Log usage
    log = UsageLogORM(
        company_id=company_id,
        user_id=created_by,
        action="interview_questions_generated",
        details=json.dumps({
            "candidate_id": candidate_id,
            "question_count": len(questions),
            "tier": result.get("tier"),
        }),
        latency_ms=result.get("latency_ms", 0.0),
        cost_usd=result.get("cost_usd", 0.0),
    )
    db.add(log)
    db.commit()
    db.refresh(record)

    return record


# ============================================================
# 34.5 — GET QUESTIONS FOR CANDIDATE
# ============================================================
def get_questions_for_candidate(
    db: Session,
    company_id: str,
    candidate_id: str,
) -> Optional[InterviewQuestionSetORM]:
    return (
        db.query(InterviewQuestionSetORM)
        .filter(
            InterviewQuestionSetORM.company_id  == company_id,
            InterviewQuestionSetORM.candidate_id == candidate_id,
            InterviewQuestionSetORM.is_deleted   == False,
        )
        .order_by(InterviewQuestionSetORM.created_at.desc())
        .first()
    )


# ============================================================
# 34.6 — GET QUESTION SET STATS
# ============================================================
def get_interview_stats(db: Session, company_id: str) -> dict:
    sets = (
        db.query(InterviewQuestionSetORM)
        .filter(
            InterviewQuestionSetORM.company_id == company_id,
            InterviewQuestionSetORM.is_deleted == False,
        )
        .all()
    )

    if not sets:
        return {
            "ok": True,
            "total_sets": 0,
            "total_questions": 0,
            "total_cost": 0.0,
            "avg_latency_ms": 0.0,
            "by_tier": {"gold": 0, "silver": 0, "bronze": 0},
        }

    by_tier = {"gold": 0, "silver": 0, "bronze": 0}
    for s in sets:
        tier = s.tier or "bronze"
        by_tier[tier] = by_tier.get(tier, 0) + 1

    return {
        "ok":              True,
        "total_sets":      len(sets),
        "total_questions": sum(s.question_count or 0 for s in sets),
        "total_cost":      round(sum(s.cost_usd or 0 for s in sets), 6),
        "avg_latency_ms":  round(
            sum(s.latency_ms or 0 for s in sets) / len(sets), 1
        ),
        "by_tier":         by_tier,
    }