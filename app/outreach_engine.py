# app/outreach_engine.py - Phase 33 AI Outreach Engine
import uuid, time, os, json
from datetime import datetime
from sqlalchemy.orm import Session
import httpx
from app.db import OutreachORM, CompanyCandidateORM, AINarrativeORM, CompanyRoleORM
from app.cost_engine import calculate_ai_cost, track_ai_call

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = "gpt-4o"
PROMPT_VERSION = "v33.1"

MESSAGE_TYPES = {
    "linkedin_connection": {"label": "LinkedIn Connection Request", "char_limit": 300, "channel": "linkedin"},
    "linkedin_inmail": {"label": "LinkedIn InMail", "char_limit": 1000, "channel": "linkedin"},
    "email": {"label": "Email Outreach", "char_limit": 2000, "channel": "email"},
    "followup": {"label": "Follow-up Message", "char_limit": 500, "channel": "linkedin"},
    "rejection": {"label": "Kind Rejection", "char_limit": 500, "channel": "email"},
}
OUTREACH_TONES = {
    "warm": "Warm, human, genuine tone.",
    "professional": "Professional, respectful tone.",
    "bold": "Bold, direct, startup-style.",
    "concise": "As short as possible. No fluff.",
}

def _fallback_outreach(name, role, message_type, tone):
    fallbacks = {
        "linkedin_connection": f"Hi {name}, I came across your profile and think you'd be a great fit for a {role} opportunity. Would love to connect!",
        "linkedin_inmail": f"SUBJECT: {role} Opportunity\n\nHi {name},\n\nYour background caught my attention for a {role} role. Would you be open to a quick call?\n\nBest regards",
        "email": f"SUBJECT: {role} Opportunity\n\nHi {name},\n\nI'd love to share details about a {role} opportunity. Would you be open to a brief call?\n\nBest regards",
        "followup": f"Hi {name}, just following up on the {role} opportunity. Happy to chat whenever works!",
        "rejection": f"Hi {name}, thank you for your interest. We've decided to move forward with other candidates, but hope our paths cross again.",
    }
    return fallbacks.get(message_type, fallbacks["linkedin_connection"])

def score_outreach_quality(message, message_type):
    score = 100
    char_limit = MESSAGE_TYPES.get(message_type, {}).get("char_limit", 300)
    if len(message) > char_limit: score -= 20
    if len(message) < 50: score -= 30
    return max(0, min(100, score))

async def generate_outreach(db, candidate_id, company_id, user_id, message_type="linkedin_connection", tone="warm", recruiter_name="", project_id=None):
    start = time.time()
    if message_type not in MESSAGE_TYPES:
        return {"error": f"Invalid message type"}
    candidate = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.id == candidate_id, CompanyCandidateORM.company_id == company_id, CompanyCandidateORM.is_deleted == False).first()
    if not candidate: return {"error": "Candidate not found"}
    role_title = candidate.role or "the role"
    narrative = ""
    cached = db.query(AINarrativeORM).filter(AINarrativeORM.candidate_id == candidate_id, AINarrativeORM.company_id == company_id, AINarrativeORM.is_deleted == False).order_by(AINarrativeORM.created_at.desc()).first()
    if cached: narrative = cached.narrative
    message = _fallback_outreach(candidate.name, role_title, message_type, tone)
    subject = ""
    tokens_in, tokens_out = 0, 0
    try:
        prompt = f"Write a {MESSAGE_TYPES[message_type]['label']} for {candidate.name} about a {role_title} role. Tone: {OUTREACH_TONES.get(tone, '')}. Max {MESSAGE_TYPES[message_type]['char_limit']} chars. Output only the message."
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{AZURE_OPENAI_ENDPOINT}openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version=2024-02-01", headers={"api-key": AZURE_OPENAI_KEY, "Content-Type": "application/json"}, json={"messages": [{"role": "user", "content": prompt}], "max_tokens": 600, "temperature": 0.75}, timeout=15.0)
            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()
            tokens_in = result.get("usage", {}).get("prompt_tokens", 0)
            tokens_out = result.get("usage", {}).get("completion_tokens", 0)
            if message_type in ("email", "linkedin_inmail") and "SUBJECT:" in content:
                lines = content.split("\n"); subject = lines[0].replace("SUBJECT:", "").strip(); message = "\n".join(lines[2:]).strip()
            else: message = content
    except Exception: pass
    latency_ms = round((time.time() - start) * 1000, 2)
    try: cost_usd = calculate_ai_cost(AZURE_OPENAI_DEPLOYMENT, tokens_in, tokens_out)
    except: cost_usd = 0.0
    quality = score_outreach_quality(message, message_type)
    outreach = OutreachORM(id=str(uuid.uuid4()), company_id=company_id, candidate_id=candidate_id, created_by=user_id, project_id=project_id, message_type=message_type, channel=MESSAGE_TYPES[message_type]["channel"], subject=subject, content=message, char_count=len(message), tone=tone, model_used=AZURE_OPENAI_DEPLOYMENT, prompt_version=PROMPT_VERSION, tokens_used=tokens_in+tokens_out, cost_usd=cost_usd, latency_ms=latency_ms, quality_score=quality, sent=False)
    db.add(outreach)
    try: db.commit()
    except: db.rollback()
    return {"outreach_id": outreach.id, "message": message, "subject": subject, "message_type": message_type, "type_label": MESSAGE_TYPES[message_type]["label"], "channel": MESSAGE_TYPES[message_type]["channel"], "char_count": len(message), "char_limit": MESSAGE_TYPES[message_type]["char_limit"], "tone": tone, "quality_score": quality, "cost_usd": cost_usd, "latency_ms": latency_ms, "candidate_name": candidate.name, "candidate_tier": candidate.tier}

async def generate_batch_outreach(db, company_id, user_id, message_type="linkedin_connection", tone="warm", project_id=None):
    candidates = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id == company_id, CompanyCandidateORM.shortlisted == True, CompanyCandidateORM.is_deleted == False).all()
    results = []; total_cost = 0.0; generated = 0; failed = 0
    for c in candidates:
        result = await generate_outreach(db, c.id, company_id, user_id, message_type, tone, project_id=project_id)
        if "error" not in result: results.append(result); total_cost += result.get("cost_usd", 0); generated += 1
        else: failed += 1
    return {"total": len(candidates), "generated": generated, "failed": failed, "total_cost": round(total_cost, 6), "results": results}

def mark_outreach_sent(db, outreach_id, company_id, sent_via="manual"):
    outreach = db.query(OutreachORM).filter(OutreachORM.id == outreach_id, OutreachORM.company_id == company_id).first()
    if not outreach: return False
    outreach.sent = True; outreach.sent_at = datetime.utcnow(); outreach.sent_via = sent_via
    try: db.commit(); return True
    except: db.rollback(); return False

def get_outreach_stats(db, company_id):
    messages = db.query(OutreachORM).filter(OutreachORM.company_id == company_id, OutreachORM.is_deleted == False).all()
    total = len(messages); sent = sum(1 for m in messages if m.sent); responded = sum(1 for m in messages if m.responded); total_cost = sum(m.cost_usd or 0 for m in messages)
    return {"total": total, "sent": sent, "unsent": total-sent, "responded": responded, "response_rate": round(responded/max(sent,1)*100,1), "total_cost": round(total_cost,4)}

def get_message_types():
    return [{"key": k, "label": v["label"], "char_limit": v["char_limit"], "channel": v["channel"]} for k, v in MESSAGE_TYPES.items()]

def get_outreach_tones():
    return [{"key": k, "description": v} for k, v in OUTREACH_TONES.items()]
