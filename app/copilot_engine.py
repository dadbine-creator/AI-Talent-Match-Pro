# ============================================================
# app/copilot_engine.py
# AI Talent Match Pro — Phase 33 Recruiter Copilot Engine
# GPT-4o powered AI assistant inside the recruiter workspace
# Pipeline health · Candidate recommendations · Next best action
# ============================================================

import uuid
import time
import json
import os
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import httpx

from app.db import (
    RecruiterCopilotORM, RecruiterProjectORM,
    ProjectCandidateORM, CompanyCandidateORM,
    OutreachORM, FeedbackEventORM
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
# SESSION TYPES
# ============================================================
SESSION_TYPES = {
    "pipeline_health": {
        "label":       "Pipeline Health Check",
        "description": "Analyze your pipeline and identify bottlenecks"
    },
    "candidate_recommendation": {
        "label":       "Candidate Recommendation",
        "description": "Which candidates to prioritize next"
    },
    "hiring_prediction": {
        "label":       "Hiring Prediction",
        "description": "Predict time to hire based on current pipeline"
    },
    "outreach_optimization": {
        "label":       "Outreach Optimization",
        "description": "Improve your outreach response rates"
    },
    "next_best_action": {
        "label":       "Next Best Action",
        "description": "What should you do right now to move faster"
    },
    "market_insight": {
        "label":       "Market Insight",
        "description": "Insights about the talent market for this role"
    },
    "free":  {
        "label":       "Free Question",
        "description": "Ask the copilot anything about your pipeline"
    }
}


# ============================================================
# STEP 1 — BUILD PIPELINE CONTEXT
# ============================================================

def build_pipeline_context(
    db: Session,
    company_id: str,
    project_id: str = None
) -> dict:
    """
    Build a rich context snapshot of the recruiter's pipeline.
    This feeds into every copilot session for accurate insights.
    """
    context = {}

    # Project details
    if project_id:
        project = db.query(RecruiterProjectORM).filter(
            RecruiterProjectORM.id == project_id,
            RecruiterProjectORM.company_id == company_id,
            RecruiterProjectORM.is_deleted == False
        ).first()

        if project:
            context["project"] = {
                "name":               project.name,
                "status":             project.status,
                "stage":              project.stage,
                "priority":           project.priority,
                "total_candidates":   project.total_candidates,
                "shortlisted":        project.shortlisted_count,
                "outreach_sent":      project.outreach_sent,
                "responses":          project.responses_received,
                "interviews":         project.interviews_scheduled,
                "offers":             project.offers_made,
                "hires":              project.hires_made,
                "target_hire_date":   project.target_hire_date.isoformat() if project.target_hire_date else None,
                "days_until_target":  (project.target_hire_date - datetime.utcnow()).days if project.target_hire_date else None
            }

            # Pipeline candidates
            pc_list = db.query(ProjectCandidateORM).filter(
                ProjectCandidateORM.project_id == project_id,
                ProjectCandidateORM.is_deleted == False
            ).all()

            stages = {}
            for pc in pc_list:
                stage = pc.stage_name or "sourcing"
                if stage not in stages:
                    stages[stage] = 0
                stages[stage] += 1

            context["pipeline_by_stage"] = stages
            context["response_rate"] = round(
                project.responses_received / max(project.outreach_sent, 1) * 100, 1
            )

    # Overall company candidates
    from sqlalchemy import func
    from app.db import CompanyCandidateORM
    candidates = db.query(CompanyCandidateORM).filter(
        CompanyCandidateORM.company_id == company_id,
        CompanyCandidateORM.is_deleted == False
    ).all()

    gold   = sum(1 for c in candidates if c.tier == "gold")
    silver = sum(1 for c in candidates if c.tier == "silver")
    bronze = sum(1 for c in candidates if c.tier == "bronze")
    avg_score = sum(c.match_score for c in candidates) / max(len(candidates), 1)

    context["candidates"] = {
        "total":  len(candidates),
        "gold":   gold,
        "silver": silver,
        "bronze": bronze,
        "avg_score": round(avg_score, 1)
    }

    # Recent outreach stats
    outreach = db.query(OutreachORM).filter(
        OutreachORM.company_id == company_id,
        OutreachORM.is_deleted == False
    ).all()

    context["outreach"] = {
        "total":      len(outreach),
        "sent":       sum(1 for o in outreach if o.sent),
        "responded":  sum(1 for o in outreach if o.responded),
        "response_rate": round(
            sum(1 for o in outreach if o.responded) /
            max(sum(1 for o in outreach if o.sent), 1) * 100, 1
        )
    }

    return context


# ============================================================
# STEP 2 — BUILD COPILOT PROMPT
# ============================================================

def build_copilot_prompt(
    session_type: str,
    context: dict,
    user_prompt: str,
    role_title: str = ""
) -> str:
    """
    Build GPT-4o prompt for the recruiter copilot.
    Combines pipeline context + session type + user question.
    """
    context_str = json.dumps(context, indent=2)

    system_prompts = {
        "pipeline_health": f"""You are an expert recruiting AI copilot analyzing a recruiter's pipeline.
Your job: identify bottlenecks, risks, and opportunities in the hiring pipeline.
Be specific, data-driven, and actionable. Use the pipeline data provided.

Pipeline Data:
{context_str}

Provide:
1. Overall pipeline health score (0-100)
2. Top 3 bottlenecks
3. Risks to hitting the hiring target
4. 3 specific actions to take today""",

        "candidate_recommendation": f"""You are an expert recruiting AI copilot recommending which candidates to prioritize.
Use the pipeline data and candidate tiers to give smart, ranked recommendations.

Pipeline Data:
{context_str}

Provide:
1. Top priority candidates to engage NOW (by tier + score)
2. Candidates to move forward in the pipeline
3. Candidates to deprioritize and why
4. Optimal next outreach targets""",

        "hiring_prediction": f"""You are an expert recruiting AI making a data-driven hiring prediction.
Analyze the pipeline velocity, response rates, and stage conversion to predict outcomes.

Pipeline Data:
{context_str}

Provide:
1. Predicted time to hire (days)
2. Probability of hitting target hire date
3. How many more candidates are needed
4. Key assumptions and confidence level""",

        "outreach_optimization": f"""You are an expert recruiting AI optimizing outreach strategy.
Analyze current outreach performance and suggest improvements.

Outreach Data:
{context_str}

Provide:
1. Current response rate assessment
2. Best message types for this role
3. Optimal timing recommendations
4. Subject line and tone improvements
5. A/B test ideas""",

        "next_best_action": f"""You are an expert recruiting AI telling the recruiter exactly what to do next.
Be specific, direct, and prioritized. No vague advice.

Pipeline Data:
{context_str}

Provide:
1. The single most important action RIGHT NOW
2. Next 3 actions in priority order
3. What to stop doing
4. Time estimate for each action""",

        "market_insight": f"""You are an expert recruiting AI providing talent market insights.
Role: {role_title}

Pipeline Data:
{context_str}

Provide:
1. Current market conditions for this role
2. Typical time to hire for similar roles
3. Competitive landscape (who else is hiring)
4. Salary/compensation insights
5. Best sourcing channels""",

        "free": f"""You are an expert recruiting AI copilot helping a recruiter.
You have full context of their pipeline and candidates.

Pipeline Data:
{context_str}

Answer the recruiter's question with:
- Specific, data-backed insights
- Actionable recommendations
- Clear next steps"""
    }

    system_prompt = system_prompts.get(session_type, system_prompts["free"])

    return f"""{system_prompt}

Recruiter's Question: {user_prompt}

Respond in a structured, clear format. Be concise but complete.
Use bullet points for actions. Be direct — no corporate filler.
End with ONE clear "Next Step" the recruiter should take in the next 30 minutes."""


# ============================================================
# STEP 3 — MAIN COPILOT RUN
# ============================================================

async def run_copilot_session(
    db: Session,
    company_id: str,
    user_id: str,
    prompt: str,
    session_type: str = "next_best_action",
    project_id: str = None,
    role_title: str = ""
) -> dict:
    """
    Run a recruiter copilot session.
    Analyzes pipeline context and returns AI insights + recommendations.
    """
    start = time.time()

    # Validate session type
    if session_type not in SESSION_TYPES:
        session_type = "free"

    # Build context
    context = build_pipeline_context(db, company_id, project_id)

    # Build prompt
    full_prompt = build_copilot_prompt(
        session_type=session_type,
        context=context,
        user_prompt=prompt,
        role_title=role_title
    )

    # Call GPT-4o
    response_text = ""
    tokens_in     = 0
    tokens_out    = 0

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AZURE_OPENAI_ENDPOINT}openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version=2024-02-01",
                headers={"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"},
                json={
                    "messages":    [{"role": "user", "content": full_prompt}],
                    "max_tokens":  800,
                    "temperature": 0.6
                },
                timeout=20.0
            )
            result        = response.json()
            response_text = result["choices"][0]["message"]["content"].strip()
            tokens_in     = result.get("usage", {}).get("prompt_tokens", 0)
            tokens_out    = result.get("usage", {}).get("completion_tokens", 0)

    except Exception:
        response_text = _fallback_copilot_response(session_type, context)

    latency_ms = round((time.time() - start) * 1000, 2)
    cost_usd   = calculate_ai_cost(AZURE_OPENAI_DEPLOYMENT, tokens_in, tokens_out)

    # Parse recommendations from response
    recommendations = _parse_recommendations(response_text)
    confidence      = _estimate_confidence(context)

    # Save session
    session = RecruiterCopilotORM(
        id=str(uuid.uuid4()),
        company_id=company_id,
        user_id=user_id,
        project_id=project_id,
        session_type=session_type,
        prompt=prompt,
        response=response_text,
        context=json.dumps(context),
        insights=response_text,
        recommendations=json.dumps(recommendations),
        confidence=confidence,
        model_version=AZURE_OPENAI_DEPLOYMENT,
        tokens_used=tokens_in + tokens_out,
        cost_usd=cost_usd,
        latency_ms=latency_ms
    )
    db.add(session)

    # Track cost
    track_ai_call(
        db=db,
        company_id=company_id,
        user_id=user_id,
        model_name=AZURE_OPENAI_DEPLOYMENT,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        cache_hit=False,
        action="ai_copilot"
    )

    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "session_id":      session.id,
        "session_type":    session_type,
        "type_label":      SESSION_TYPES[session_type]["label"],
        "response":        response_text,
        "recommendations": recommendations,
        "confidence":      confidence,
        "context_summary": {
            "total_candidates": context.get("candidates", {}).get("total", 0),
            "outreach_sent":    context.get("outreach", {}).get("sent", 0),
            "response_rate":    context.get("outreach", {}).get("response_rate", 0)
        },
        "cost_usd":        cost_usd,
        "tokens_in":       tokens_in,
        "tokens_out":      tokens_out,
        "latency_ms":      latency_ms,
        "prompt_version":  PROMPT_VERSION
    }


# ============================================================
# STEP 4 — SUBMIT FEEDBACK
# ============================================================

def submit_copilot_feedback(
    db: Session,
    session_id: str,
    company_id: str,
    helpful: bool,
    acted_on: bool = False
) -> bool:
    """Record recruiter feedback on copilot session."""
    session = db.query(RecruiterCopilotORM).filter(
        RecruiterCopilotORM.id == session_id,
        RecruiterCopilotORM.company_id == company_id
    ).first()

    if not session:
        return False

    session.helpful  = helpful
    session.acted_on = acted_on

    try:
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False


# ============================================================
# STEP 5 — GET COPILOT HISTORY
# ============================================================

def get_copilot_history(
    db: Session,
    company_id: str,
    project_id: str = None,
    limit: int = 20
) -> list:
    """Get recent copilot sessions for a company/project."""
    query = db.query(RecruiterCopilotORM).filter(
        RecruiterCopilotORM.company_id == company_id
    )
    if project_id:
        query = query.filter(RecruiterCopilotORM.project_id == project_id)

    sessions = query.order_by(
        RecruiterCopilotORM.created_at.desc()
    ).limit(limit).all()

    return [
        {
            "session_id":   s.id,
            "session_type": s.session_type,
            "type_label":   SESSION_TYPES.get(s.session_type, {}).get("label", s.session_type),
            "prompt":       s.prompt[:100] + "..." if len(s.prompt) > 100 else s.prompt,
            "response":     s.response[:200] + "..." if len(s.response) > 200 else s.response,
            "confidence":   s.confidence,
            "helpful":      s.helpful,
            "acted_on":     s.acted_on,
            "cost_usd":     s.cost_usd,
            "created_at":   s.created_at.isoformat()
        }
        for s in sessions
    ]


# ============================================================
# STEP 6 — GET COPILOT STATS
# ============================================================

def get_copilot_stats(db: Session, company_id: str) -> dict:
    """Get copilot usage stats for dashboard."""
    sessions = db.query(RecruiterCopilotORM).filter(
        RecruiterCopilotORM.company_id == company_id
    ).all()

    total      = len(sessions)
    helpful    = sum(1 for s in sessions if s.helpful == True)
    acted_on   = sum(1 for s in sessions if s.acted_on == True)
    total_cost = sum(s.cost_usd or 0 for s in sessions)

    by_type = {}
    for st in SESSION_TYPES:
        type_sessions = [s for s in sessions if s.session_type == st]
        by_type[st] = len(type_sessions)

    return {
        "total_sessions":  total,
        "helpful_rate":    round(helpful / max(total, 1) * 100, 1),
        "acted_on_rate":   round(acted_on / max(total, 1) * 100, 1),
        "total_cost":      round(total_cost, 4),
        "by_type":         by_type,
        "avg_confidence":  round(
            sum(s.confidence or 0 for s in sessions) / max(total, 1), 2
        )
    }


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _parse_recommendations(response: str) -> list:
    """Extract bullet point recommendations from response."""
    recommendations = []
    lines = response.split('\n')
    for line in lines:
        line = line.strip()
        if line.startswith(('•', '-', '*', '1.', '2.', '3.', '4.', '5.')):
            clean = line.lstrip('•-*0123456789. ').strip()
            if clean and len(clean) > 10:
                recommendations.append(clean)
    return recommendations[:6]  # max 6 recommendations


def _estimate_confidence(context: dict) -> float:
    """Estimate AI confidence based on data richness."""
    score = 0.5  # base

    candidates = context.get("candidates", {})
    if candidates.get("total", 0) >= 5:
        score += 0.1
    if candidates.get("total", 0) >= 20:
        score += 0.1

    outreach = context.get("outreach", {})
    if outreach.get("sent", 0) >= 3:
        score += 0.1
    if outreach.get("response_rate", 0) > 0:
        score += 0.1

    if context.get("project"):
        score += 0.1

    return round(min(0.95, score), 2)


def _fallback_copilot_response(session_type: str, context: dict) -> str:
    """Fallback response when API fails."""
    candidates = context.get("candidates", {})
    outreach   = context.get("outreach", {})

    fallbacks = {
        "pipeline_health":          f"Pipeline has {candidates.get('total', 0)} candidates. {candidates.get('gold', 0)} gold tier. Response rate: {outreach.get('response_rate', 0)}%. Focus on engaging your top gold candidates first.",
        "candidate_recommendation": f"Prioritize your {candidates.get('gold', 0)} gold candidates for immediate outreach. Follow up with silver tier next. Bronze candidates should be deprioritized unless gold/silver pipeline is thin.",
        "hiring_prediction":        "Based on current pipeline velocity, estimated time to hire is 2-4 weeks assuming consistent outreach and follow-up.",
        "outreach_optimization":    "Increase personalization in your messages. LinkedIn InMail has higher response rates than connection requests for senior roles. Send follow-ups 5-7 days after initial outreach.",
        "next_best_action":         "1. Generate outreach for your top gold candidate now\n2. Follow up with candidates who haven't responded in 5+ days\n3. Move responded candidates to the next pipeline stage",
        "market_insight":           "The talent market for this role is competitive. Focus on passive candidates and differentiate with your company culture and growth opportunity.",
        "free":                     "I'm here to help with your recruiting pipeline. Ask me about candidate prioritization, outreach optimization, or pipeline health."
    }

    return fallbacks.get(session_type, fallbacks["free"])


# ============================================================
# HELPERS
# ============================================================

def get_session_types() -> list:
    """Return all available session types for UI."""
    return [
        {"key": k, "label": v["label"], "description": v["description"]}
        for k, v in SESSION_TYPES.items()
    ]