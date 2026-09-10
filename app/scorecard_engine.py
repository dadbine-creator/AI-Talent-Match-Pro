"""
============================================================
PHASE 35 — AI SCORECARDS ENGINE
Generates structured, multi-dimensional scorecards per
candidate per role. GPT-4o powered. Collaborative scoring.
Human vs AI score comparison.
============================================================
"""

import os
import json
import uuid
import time
import logging
from datetime import datetime
from typing import Optional, List

from openai import AzureOpenAI
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db import (
    ScorecardORM,
    CompanyCandidateORM,
    CompanyRoleORM,
    RecruiterProjectORM,
    UsageLogORM,
)

logger = logging.getLogger(__name__)

# ── Azure OpenAI ─────────────────────────────────────────
client = None
try:
    client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY", ""),
    api_version="2024-02-01",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
)
except Exception:
    client = None
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# ── Scorecard dimensions ──────────────────────────────────
DIMENSIONS = [
    "Technical Skills",
    "Leadership & Management",
    "Culture & Values Fit",
    "Communication",
    "Role Fit",
    "Growth Potential",
]

# ── Templates per role type ───────────────────────────────
ROLE_TEMPLATES = {
    "engineering": [
        "Technical Skills",
        "System Design",
        "Problem Solving",
        "Code Quality",
        "Communication",
        "Growth Potential",
    ],
    "sales": [
        "Pipeline Management",
        "Closing Ability",
        "Communication",
        "Culture & Values Fit",
        "Role Fit",
        "Growth Potential",
    ],
    "marketing": [
        "Strategy & Vision",
        "Data & Analytics",
        "Communication",
        "Culture & Values Fit",
        "Role Fit",
        "Growth Potential",
    ],
    "product": [
        "Product Thinking",
        "Technical Skills",
        "Leadership & Management",
        "Communication",
        "Role Fit",
        "Growth Potential",
    ],
    "default": DIMENSIONS,
}


def get_template_for_role(role_title: str) -> List[str]:
    """Select scorecard template based on role title."""
    title_lower = (role_title or "").lower()
    if any(k in title_lower for k in ["engineer", "developer", "technical", "backend", "frontend", "ml", "data"]):
        return ROLE_TEMPLATES["engineering"]
    elif any(k in title_lower for k in ["sales", "account", "business development", "revenue"]):
        return ROLE_TEMPLATES["sales"]
    elif any(k in title_lower for k in ["marketing", "growth", "demand", "brand"]):
        return ROLE_TEMPLATES["marketing"]
    elif any(k in title_lower for k in ["product", "pm", "program"]):
        return ROLE_TEMPLATES["product"]
    return ROLE_TEMPLATES["default"]


# ============================================================
# 35.1 — GENERATE AI SCORECARD
# ============================================================

async def generate_scorecard(
    candidate_name: str,
    candidate_role: str,
    candidate_tier: str,
    candidate_score: float,
    candidate_analysis: str,
    job_title: str,
    job_description: str,
    focus_areas: Optional[str] = None,
) -> dict:
    """Generate a structured AI scorecard for a candidate."""
    start = time.time()

    dimensions = get_template_for_role(job_title)
    if focus_areas:
        extra = [f.strip() for f in focus_areas.split(",") if f.strip()]
        dimensions = list(dict.fromkeys(dimensions + extra))

    system_prompt = """You are an expert recruiter and talent evaluator.
Generate a precise, structured scorecard for a candidate being evaluated for a specific role.
Score each dimension 1-10. Be specific, data-driven, and calibrated — not every candidate is a 10.
Return ONLY valid JSON. No preamble, no markdown fences."""

    user_prompt = f"""CANDIDATE:
- Name: {candidate_name}
- Current Role: {candidate_role}
- AI Match Tier: {candidate_tier.upper()} ({candidate_score:.0f}% match)
- AI Analysis: {candidate_analysis[:500] if candidate_analysis else 'Not available'}

ROLE BEING HIRED FOR: {job_title}
DESCRIPTION: {job_description[:400] if job_description else 'Not provided'}

SCORECARD DIMENSIONS: {dimensions}

Return a JSON object with these exact fields:
{{
  "dimensions": [
    {{
      "name": "dimension name",
      "score": 1-10,
      "weight": 1.0,
      "justification": "one precise sentence why this score",
      "evidence": "specific evidence from their profile",
      "flag": "strength|neutral|concern"
    }}
  ],
  "overall_score": weighted average 1-10,
  "recommendation": "strong_yes|yes|maybe|no",
  "recommendation_label": "Strong Hire|Hire|Consider|Pass",
  "summary": "2-3 sentence executive summary",
  "strengths": ["top 3 strengths as strings"],
  "concerns": ["top 2 concerns as strings"],
  "vs_ai_score": {{
    "ai_score": {candidate_score},
    "scorecard_score": calculated,
    "alignment": "aligned|slight_variance|significant_variance",
    "note": "one sentence explaining any gap"
  }}
}}"""

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        latency_ms  = (time.time() - start) * 1000
        raw         = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        scorecard   = json.loads(raw)
        tokens_used = response.usage.total_tokens if response.usage else 0
        cost_usd    = tokens_used * 0.000005

        return {
            "ok":          True,
            "scorecard":   scorecard,
            "dimensions":  scorecard.get("dimensions", []),
            "overall_score": scorecard.get("overall_score", 0),
            "recommendation": scorecard.get("recommendation", "maybe"),
            "recommendation_label": scorecard.get("recommendation_label", "Consider"),
            "summary":     scorecard.get("summary", ""),
            "strengths":   scorecard.get("strengths", []),
            "concerns":    scorecard.get("concerns", []),
            "vs_ai_score": scorecard.get("vs_ai_score", {}),
            "tokens_used": tokens_used,
            "cost_usd":    round(cost_usd, 6),
            "latency_ms":  round(latency_ms, 1),
            "model":       DEPLOYMENT,
            "template":    job_title,
        }

    except json.JSONDecodeError as e:
        logger.error(f"Scorecard JSON parse error: {e}")
        return {
            "ok":        True,
            "scorecard": _fallback_scorecard(dimensions, candidate_score, candidate_tier),
            "latency_ms": round((time.time() - start) * 1000, 1),
            "fallback":  True,
        }
    except Exception as e:
        logger.error(f"Scorecard generation error: {e}")
        return {
            "ok":        False,
            "error":     str(e),
            "scorecard": _fallback_scorecard(dimensions, candidate_score, candidate_tier),
            "fallback":  True,
        }


# ============================================================
# 35.2 — FALLBACK SCORECARD
# ============================================================

def _fallback_scorecard(dimensions: List[str], ai_score: float, tier: str) -> dict:
    """Fallback scorecard when API fails."""
    base = 8 if tier == "gold" else 7 if tier == "silver" else 6
    dims = [
        {
            "name":          d,
            "score":         base + (1 if i < 2 else 0),
            "weight":        1.0,
            "justification": "Score based on AI match analysis.",
            "evidence":      "Derived from candidate profile.",
            "flag":          "strength" if i < 2 else "neutral",
        }
        for i, d in enumerate(dimensions)
    ]
    overall = round(sum(d["score"] for d in dims) / len(dims), 1)
    rec     = "strong_yes" if tier == "gold" else "yes" if tier == "silver" else "maybe"
    rec_lbl = "Strong Hire" if tier == "gold" else "Hire" if tier == "silver" else "Consider"

    return {
        "dimensions":          dims,
        "overall_score":       overall,
        "recommendation":      rec,
        "recommendation_label": rec_lbl,
        "summary":             f"Candidate shows strong alignment with role requirements. AI match score: {ai_score:.0f}%.",
        "strengths":           ["Strong role alignment", "Good tier match", "Meets core requirements"],
        "concerns":            ["Further evaluation recommended", "Verify specific skill depth"],
        "vs_ai_score": {
            "ai_score":    ai_score,
            "scorecard_score": overall * 10,
            "alignment":  "aligned",
            "note":       "Scorecard aligns with AI match score.",
        },
    }


# ============================================================
# 35.3 — SAVE SCORECARD TO DB
# ============================================================

def save_scorecard(
    db: Session,
    company_id: str,
    candidate_id: str,
    created_by: str,
    result: dict,
    job_id: Optional[str] = None,
    project_id: Optional[str] = None,
    focus_areas: Optional[str] = None,
) -> ScorecardORM:
    scorecard_data = result.get("scorecard", {})

    record = ScorecardORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        candidate_id=candidate_id,
        job_id=job_id,
        project_id=project_id,
        created_by=created_by,
        scorecard_json=json.dumps(scorecard_data),
        dimensions_json=json.dumps(result.get("dimensions", [])),
        overall_score=result.get("overall_score", 0),
        recommendation=result.get("recommendation", "maybe"),
        recommendation_label=result.get("recommendation_label", "Consider"),
        summary=result.get("summary", ""),
        strengths_json=json.dumps(result.get("strengths", [])),
        concerns_json=json.dumps(result.get("concerns", [])),
        vs_ai_score_json=json.dumps(result.get("vs_ai_score", {})),
        ai_match_score=result.get("vs_ai_score", {}).get("ai_score", 0),
        focus_areas=focus_areas,
        model_used=result.get("model", DEPLOYMENT),
        prompt_version="v35.1",
        tokens_used=result.get("tokens_used", 0),
        cost_usd=result.get("cost_usd", 0.0),
        latency_ms=result.get("latency_ms", 0.0),
        is_fallback=result.get("fallback", False),
    )

    db.add(record)

    # Usage log
    usage = UsageLogORM(
        company_id=company_id,
        user_id=created_by,
        action="scorecard_generated",
        details=json.dumps({
            "candidate_id":   candidate_id,
            "overall_score":  result.get("overall_score"),
            "recommendation": result.get("recommendation"),
        }),
        latency_ms=result.get("latency_ms", 0.0),
        cost_usd=result.get("cost_usd", 0.0),
    )
    db.add(usage)
    db.commit()
    db.refresh(record)
    return record


# ============================================================
# 35.4 — ADD HUMAN SCORE (collaborative)
# ============================================================

def add_human_score(
    db: Session,
    scorecard_id: str,
    company_id: str,
    scorer_id: str,
    scorer_name: str,
    human_scores: dict,
    human_notes: Optional[str] = None,
) -> ScorecardORM:
    """Add a human recruiter's score to an existing scorecard."""
    record = db.query(ScorecardORM).filter(
        ScorecardORM.id         == scorecard_id,
        ScorecardORM.company_id == company_id,
        ScorecardORM.is_deleted == False,
    ).first()

    if not record:
        raise ValueError(f"Scorecard {scorecard_id} not found")

    # Load existing human scores
    existing = json.loads(record.human_scores_json or "[]")
    existing.append({
        "scorer_id":   scorer_id,
        "scorer_name": scorer_name,
        "scores":      human_scores,
        "notes":       human_notes,
        "scored_at":   datetime.utcnow().isoformat(),
    })
    record.human_scores_json = json.dumps(existing)

    # Compute average human score
    all_scores = []
    for entry in existing:
        vals = list(entry["scores"].values())
        if vals:
            all_scores.append(sum(vals) / len(vals))

    if all_scores:
        record.avg_human_score = round(sum(all_scores) / len(all_scores), 2)
        record.human_scorer_count = len(existing)

    db.commit()
    db.refresh(record)
    return record


# ============================================================
# 35.5 — GET SCORECARD
# ============================================================

def get_scorecard(
    db: Session,
    company_id: str,
    candidate_id: str,
) -> Optional[ScorecardORM]:
    return (
        db.query(ScorecardORM)
        .filter(
            ScorecardORM.company_id  == company_id,
            ScorecardORM.candidate_id == candidate_id,
            ScorecardORM.is_deleted  == False,
        )
        .order_by(desc(ScorecardORM.created_at))
        .first()
    )


def get_scorecard_by_id(
    db: Session,
    scorecard_id: str,
    company_id: str,
) -> Optional[ScorecardORM]:
    return db.query(ScorecardORM).filter(
        ScorecardORM.id         == scorecard_id,
        ScorecardORM.company_id == company_id,
        ScorecardORM.is_deleted == False,
    ).first()


# ============================================================
# 35.6 — SCORECARD STATS
# ============================================================

def get_scorecard_stats(db: Session, company_id: str) -> dict:
    records = db.query(ScorecardORM).filter(
        ScorecardORM.company_id == company_id,
        ScorecardORM.is_deleted == False,
    ).all()

    if not records:
        return {
            "ok":             True,
            "total":          0,
            "avg_score":      0,
            "recommendations": {},
            "total_cost":     0.0,
            "human_scored":   0,
            "ai_human_drift": 0.0,
        }

    recs = {}
    for r in records:
        rec = r.recommendation or "maybe"
        recs[rec] = recs.get(rec, 0) + 1

    human_scored = [r for r in records if r.avg_human_score]
    drift = 0.0
    if human_scored:
        drifts = [abs((r.avg_human_score * 10) - r.ai_match_score) for r in human_scored]
        drift  = round(sum(drifts) / len(drifts), 1)

    return {
        "ok":              True,
        "total":           len(records),
        "avg_score":       round(sum(r.overall_score or 0 for r in records) / len(records), 1),
        "recommendations": recs,
        "total_cost":      round(sum(r.cost_usd or 0 for r in records), 6),
        "human_scored":    len(human_scored),
        "ai_human_drift":  drift,
    }