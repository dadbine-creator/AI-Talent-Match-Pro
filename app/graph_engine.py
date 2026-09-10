import os, uuid, json, logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.db import GraphNodeORM, GraphEdgeORM, BillingEventORM, CompanyCandidateORM, CompanyORM, UsageLogORM

logger = logging.getLogger(__name__)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_BUSINESS = os.getenv("STRIPE_PRICE_BUSINESS", "price_1TFDd5JEOljoVrx0eoAVExvJ")
STRIPE_PRICE_CORPORATE = os.getenv("STRIPE_PRICE_CORPORATE", "price_corporate")
STRIPE_PRICE_ENTERPRISE = os.getenv("STRIPE_PRICE_ENTERPRISE", "price_enterprise")

# NOTE: Billing/checkout is consolidated on Paddle; app/main.py `PLANS` is the canonical
# source for pricing + entitlements. This dict only backs the informational /api/billing/plans
# and /api/billing/status views. price_id is None because Stripe self-serve checkout is retired
# (the old placeholder IDs like "price_corporate" errored at Stripe). Prices mirror main.PLANS.
PLANS = {
    "free": {"name": "Free", "price_id": None, "price_month": 0, "candidates": 10, "ai_calls": 50, "api_calls": 1000, "features": ["Basic scoring", "5 outreach messages/mo"]},
    "business": {"name": "Business", "price_id": None, "price_month": 89, "candidates": 500, "ai_calls": 2000, "api_calls": 50000, "features": ["Everything in Free", "AI Copilot", "Forecast Engine", "Signals", "Webhooks"]},
    "corporate": {"name": "Corporate", "price_id": None, "price_month": 299, "candidates": 2000, "ai_calls": 10000, "api_calls": 200000, "features": ["Everything in Business", "AI Coaching", "Talent Graph", "Partner Marketplace", "SSO"]},
    "enterprise": {"name": "Enterprise", "price_id": None, "price_month": 999, "candidates": -1, "ai_calls": -1, "api_calls": -1, "features": ["Everything in Corporate", "Unlimited", "SLA", "Dedicated support"]},
}

def _compute_similarity(c1, c2):
    score = 0.0
    if c1.role and c2.role:
        r1 = set(c1.role.lower().split()); r2 = set(c2.role.lower().split())
        overlap = len(r1 & r2) / max(len(r1 | r2), 1)
        score += overlap * 0.4
    if c1.match_score and c2.match_score:
        diff = abs(c1.match_score - c2.match_score)
        score += max(0, (1 - diff / 30)) * 0.3
    if c1.silent_skill and c2.silent_skill:
        if c1.silent_skill.lower() == c2.silent_skill.lower(): score += 0.3
    if c1.tier == c2.tier: score += 0.1
    return round(min(1.0, score), 2)

def _upsert_node(db, company_id, node_type, entity_id, metadata=None):
    existing = db.query(GraphNodeORM).filter(GraphNodeORM.company_id==company_id, GraphNodeORM.entity_id==entity_id).first()
    if existing:
        existing.metadata_json = json.dumps(metadata or {}); existing.updated_at = datetime.utcnow(); return None
    node = GraphNodeORM(id=str(uuid.uuid4()), company_id=company_id, node_type=node_type, entity_id=entity_id, metadata_json=json.dumps(metadata or {}), embedding_json=json.dumps([]))
    db.add(node); return node

def _upsert_edge(db, company_id, source_id, target_id, relation, weight=1.0, metadata=None):
    existing = db.query(GraphEdgeORM).filter(GraphEdgeORM.company_id==company_id, GraphEdgeORM.source_id==source_id, GraphEdgeORM.target_id==target_id, GraphEdgeORM.relation==relation).first()
    if existing:
        existing.weight = weight; existing.updated_at = datetime.utcnow(); return None
    edge = GraphEdgeORM(id=str(uuid.uuid4()), company_id=company_id, source_id=source_id, target_id=target_id, relation=relation, weight=weight, metadata_json=json.dumps(metadata or {}))
    db.add(edge); return edge

def build_candidate_graph(db, company_id):
    candidates = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id, CompanyCandidateORM.is_deleted==False).all()
    nodes_created = edges_created = 0
    for c in candidates:
        n = _upsert_node(db, company_id, "candidate", c.id, {"name": c.name, "role": c.role, "tier": c.tier, "score": c.match_score})
        if n: nodes_created += 1
        if c.silent_skill:
            skill_id = f"skill_{c.silent_skill.lower().replace(' ','_')}"
            _upsert_node(db, company_id, "skill", skill_id, {"name": c.silent_skill})
            e = _upsert_edge(db, company_id, c.id, skill_id, "has_skill")
            if e: edges_created += 1
    for i, c1 in enumerate(candidates):
        for c2 in candidates[i+1:]:
            sim = _compute_similarity(c1, c2)
            if sim >= 0.5:
                e = _upsert_edge(db, company_id, c1.id, c2.id, "similar_to", weight=sim)
                if e: edges_created += 1
    try: db.commit()
    except: db.rollback()
    return {"ok": True, "nodes_created": nodes_created, "edges_created": edges_created, "candidates": len(candidates)}

def get_similar_candidates(db, company_id, candidate_id, limit=5):
    edges = db.query(GraphEdgeORM).filter(GraphEdgeORM.company_id==company_id, GraphEdgeORM.relation=="similar_to", (GraphEdgeORM.source_id==candidate_id)|(GraphEdgeORM.target_id==candidate_id)).order_by(desc(GraphEdgeORM.weight)).limit(limit).all()
    results = []
    for edge in edges:
        peer_id = edge.target_id if edge.source_id == candidate_id else edge.source_id
        peer = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.id==peer_id, CompanyCandidateORM.company_id==company_id, CompanyCandidateORM.is_deleted==False).first()
        if peer: results.append({"id": peer.id, "name": peer.name, "role": peer.role, "tier": peer.tier, "score": peer.match_score, "similarity": round(edge.weight*100,1)})
    return results

def get_lookalike_candidates(db, company_id, role, limit=5):
    if not role: return []
    candidates = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id, CompanyCandidateORM.is_deleted==False, CompanyCandidateORM.tier.in_(["gold","silver"])).order_by(desc(CompanyCandidateORM.match_score)).all()
    role_words = set(role.lower().split()); scored = []
    for c in candidates:
        if not c.role: continue
        c_words = set(c.role.lower().split()); overlap = len(role_words & c_words) / max(len(role_words | c_words), 1)
        final = round((overlap * 0.6 + (c.match_score or 0) / 100 * 0.4) * 100, 1)
        scored.append({"candidate": c, "match": final})
    scored.sort(key=lambda x: x["match"], reverse=True)
    return [{"id": s["candidate"].id, "name": s["candidate"].name, "role": s["candidate"].role, "tier": s["candidate"].tier, "score": s["candidate"].match_score, "match": s["match"]} for s in scored[:limit]]

def get_hidden_connections(db, company_id, candidate_id):
    candidate = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.id==candidate_id, CompanyCandidateORM.company_id==company_id).first()
    if not candidate: return {"ok": False, "error": "Candidate not found"}
    similar = get_similar_candidates(db, company_id, candidate_id, limit=3)
    return {"ok": True, "candidate": {"id": candidate.id, "name": candidate.name, "role": candidate.role}, "similar": similar, "total_connections": len(similar)}

def get_graph_analytics(db, company_id):
    total_nodes = db.query(GraphNodeORM).filter(GraphNodeORM.company_id==company_id).count()
    total_edges = db.query(GraphEdgeORM).filter(GraphEdgeORM.company_id==company_id).count()
    total_cands = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id, CompanyCandidateORM.is_deleted==False).count()
    sim_edges = db.query(GraphEdgeORM).filter(GraphEdgeORM.company_id==company_id, GraphEdgeORM.relation=="similar_to").all()
    avg_sim = round(sum(e.weight for e in sim_edges) / max(len(sim_edges),1) * 100, 1)
    coverage = round(total_nodes / max(total_cands,1) * 100, 1)
    insights = []
    if coverage < 50: insights.append(f"Graph coverage is {coverage}% — build the graph to unlock similarity search")
    if avg_sim > 70: insights.append(f"High similarity cluster detected — {avg_sim}% average match")
    if total_edges > total_nodes * 2: insights.append("Dense talent graph — rich connections detected")
    if not insights: insights.append("Build the talent graph to unlock lookalike search and hidden connections")
    return {"ok": True, "total_nodes": total_nodes, "total_edges": total_edges, "similarity_edges": len(sim_edges), "avg_similarity": avg_sim, "graph_coverage": coverage, "insights": insights}

def get_plans():
    return {"ok": True, "plans": list(PLANS.values())}

def get_billing_status(db, company_id):
    company = db.query(CompanyORM).filter(CompanyORM.id==company_id).first()
    if not company: return {"ok": False, "error": "Company not found"}
    plan_key = company.plan or "free"; plan = PLANS.get(plan_key, PLANS["free"])
    since = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)
    try:
        ai_usage = db.query(UsageLogORM).filter(UsageLogORM.company_id==company_id, UsageLogORM.created_at>=since, UsageLogORM.action.in_(["ai_grade","ai_narrative","ai_outreach","ai_copilot"])).count()
        api_usage = db.query(UsageLogORM).filter(UsageLogORM.company_id==company_id, UsageLogORM.created_at>=since).count()
        cand_count = db.query(CompanyCandidateORM).filter(CompanyCandidateORM.company_id==company_id, CompanyCandidateORM.is_deleted==False).count()
    except: ai_usage = api_usage = cand_count = 0
    def pct(used, limit): return 0 if limit == -1 else round(used/max(limit,1)*100,1)
    return {"ok": True, "plan": plan_key, "plan_name": plan["name"], "price_month": plan["price_month"], "features": plan["features"], "usage": {"candidates": {"used": cand_count, "limit": plan["candidates"], "pct": pct(cand_count, plan["candidates"])}, "ai_calls": {"used": ai_usage, "limit": plan["ai_calls"], "pct": pct(ai_usage, plan["ai_calls"])}, "api_calls": {"used": api_usage, "limit": plan["api_calls"], "pct": pct(api_usage, plan["api_calls"])}}, "stripe_customer_id": company.stripe_customer_id, "period_start": since.isoformat()}

def create_checkout_session(company, plan_key, return_url):
    if not STRIPE_SECRET_KEY: return {"ok": False, "demo": True, "message": "Stripe not configured — add STRIPE_SECRET_KEY to .env", "plan": plan_key}
    plan = PLANS.get(plan_key)
    if not plan or not plan.get("price_id"): return {"ok": False, "error": f"Invalid plan: {plan_key}"}
    try:
        import stripe; stripe.api_key = STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(customer=company.stripe_customer_id or None, payment_method_types=["card"], line_items=[{"price": plan["price_id"], "quantity": 1}], mode="subscription", success_url=f"{return_url}?success=true&plan={plan_key}", cancel_url=f"{return_url}?cancelled=true", metadata={"company_id": company.id, "plan": plan_key})
        return {"ok": True, "checkout_url": session.url, "session_id": session.id}
    except Exception as e: return {"ok": False, "error": str(e)}

def handle_stripe_webhook(db, payload, sig_header):
    if not STRIPE_SECRET_KEY: return {"ok": True, "message": "Stripe not configured"}
    try:
        import stripe; stripe.api_key = STRIPE_SECRET_KEY
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e: return {"ok": False, "error": str(e)}
    event_type = event["type"]; data = event["data"]["object"]
    try:
        company_id = data.get("metadata", {}).get("company_id")
        if company_id:
            log = BillingEventORM(id=str(uuid.uuid4()), company_id=company_id, event_type=event_type, stripe_event_id=event["id"], amount_cents=data.get("amount_total", 0) or 0, metadata_json=json.dumps({}))
            db.add(log)
            if event_type in ("checkout.session.completed", "invoice.payment_succeeded"):
                plan = data.get("metadata", {}).get("plan", "business")
                company = db.query(CompanyORM).filter(CompanyORM.id==company_id).first()
                if company: company.plan = plan
            db.commit()
    except: db.rollback()
    return {"ok": True, "event": event_type}

def get_billing_invoices(db, company_id):
    events = db.query(BillingEventORM).filter(BillingEventORM.company_id==company_id).order_by(desc(BillingEventORM.created_at)).limit(20).all()
    return [{"id": e.id, "event_type": e.event_type, "amount": e.amount_cents/100 if e.amount_cents else 0, "currency": e.currency, "created_at": e.created_at.isoformat()} for e in events]
