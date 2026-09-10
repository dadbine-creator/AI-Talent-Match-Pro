# team_dna.py
# ============================================================
# AI Talent Match Pro — Team DNA
#
# Learns what "good" looks like at ONE specific company by reading 2-5
# exemplar employees the recruiter already rates highly, then scores new
# candidates against that instead of against a pasted job description.
#
# Two hard rules run through this file:
#
#   1. Job-relevant signals ONLY. The prompt forbids age, gender, ethnicity,
#      nationality, religion, school prestige, name origin, photo-based traits,
#      personality type and "culture fit" as a personal characteristic, and a
#      post-filter drops anything that slips through anyway. A tool that learns
#      from your current team will happily learn your current team's
#      demographics if you let it — so we don't let it.
#   2. Never fabricate. Unparseable model output raises TeamDNAError and the
#      caller returns an honest error. There is no default score.
# ============================================================
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import List, Optional

from app.ai_engine import get_openai_client

logger = logging.getLogger(__name__)

MIN_PROFILES = 2
MAX_PROFILES = 5
MAX_PROFILE_CHARS = 6000       # per exemplar, so 5 of them still fit comfortably
MAX_FEEDBACK_EXAMPLES = 20


class TeamDNAError(Exception):
    """Raised when the model is unavailable or returns unusable output.

    Always surfaced to the user as an honest failure — never swallowed into
    a fabricated trait list or score.
    """


# ============================================================
# BIAS GUARDRAILS
# ============================================================

# Applied to model output as a backstop. The prompt is the primary control;
# this catches the cases where it is ignored. Substring match on a lowercased
# trait + evidence string.
_FORBIDDEN_PATTERNS = [
    r"\bage[ds]?\b", r"\byears? old\b", r"\byoung\b", r"\bolder\b", r"\belderly\b",
    r"\bmillennial\b", r"\bgen[ -]?z\b", r"\bboomer\b",
    r"\bgender\b", r"\bmale\b", r"\bfemale\b", r"\bman\b", r"\bwoman\b", r"\bhe\b", r"\bshe\b",
    r"\bethnic", r"\brac(e|ial)\b", r"\bnationalit", r"\bcitizen(ship)?\b", r"\bimmigrant\b",
    r"\bvisa\b", r"\breligio", r"\bchurch\b", r"\bmuslim\b", r"\bjewish\b", r"\bchristian\b",
    r"\bivy league\b", r"\btier[ -]?1 (school|university)\b", r"\bprestigious (school|university)\b",
    r"\belite (school|university|college)\b", r"\balma mater\b",
    r"\bname (sounds|origin|suggests)\b", r"\bphoto\b", r"\bappearance\b", r"\battractive\b",
    r"\bpersonality type\b", r"\bmyers[- ]?briggs\b", r"\bmbti\b", r"\benneagram\b",
    r"\bdisc profile\b", r"\bintrovert\b", r"\bextrovert\b",
    r"\bculture fit\b", r"\bculture-fit\b", r"\bcultural fit\b",
    r"\bmarital status\b", r"\bmarried\b", r"\bchildren\b", r"\bpregnan",
    r"\bdisabilit", r"\bhealth condition\b", r"\bsexual orientation\b",
]
_FORBIDDEN_RE = re.compile("|".join(_FORBIDDEN_PATTERNS), re.IGNORECASE)


def _violates_guardrails(*fields: Optional[str]) -> bool:
    blob = " ".join(f for f in fields if f)
    return bool(_FORBIDDEN_RE.search(blob))


_GUARDRAIL_BLOCK = """
HARD CONSTRAINTS — these override every other instruction:

NEVER extract, infer, mention or use as a signal:
  - age, date of birth, graduation year as a proxy for age, generation
  - gender, pronouns, or any gendered description
  - ethnicity, race, nationality, citizenship, visa status, immigration status
  - religion or religious affiliation
  - school/university PRESTIGE or ranking (the FIELD studied is fine; "went to a
    top-tier school" is not)
  - name origin or what a name implies about a person
  - anything derived from a photo or physical appearance
  - personality type, MBTI, DISC, enneagram, introvert/extrovert
  - "culture fit" as a personal characteristic
  - marital status, family status, health, disability, sexual orientation

Extract ONLY job-relevant patterns:
  - concrete skills and technologies actually used
  - scope of ownership (team size, budget, systems owned, blast radius)
  - career trajectory (direction and pace of responsibility change)
  - problem domains worked in
  - technical depth and where it sits

EVIDENCE RULE: every trait must quote or closely paraphrase a specific span of
the source text. If you cannot point at concrete evidence, DROP the trait. A
short honest list beats a long speculative one.
""".strip()


# ============================================================
# TRAIT EXTRACTION
# ============================================================

def build_dna_prompt(profiles: List[dict]) -> str:
    """profiles: [{"name": str, "raw_text": str}]"""
    roster = "\n\n".join(
        f"[Employee {i + 1}] {(p.get('name') or f'Employee {i + 1}')}\n"
        f"{(p.get('raw_text') or '').strip()[:MAX_PROFILE_CHARS]}"
        for i, p in enumerate(profiles)
    )
    return f"""
You are the Team DNA engine for "AI Talent Match Pro."

Below are {len(profiles)} people who ALREADY WORK at this company and who the
hiring team considers excellent. Your job is to identify what they genuinely
have in common professionally, so new candidates can be compared against it.

{_GUARDRAIL_BLOCK}

A trait only counts as SHARED if it appears in at least 2 of the {len(profiles)}
profiles. Weight it 1-10 by how strongly and consistently the evidence supports
it — not by how impressive it sounds.

ANTI-SIGNALS are patterns visibly ABSENT across this whole group (for example
"no one here came from big-agency consulting"). State them as observations about
the group, never as a rule about who to reject.

EXEMPLAR EMPLOYEES:
{roster}

Return ONLY this JSON (no markdown fence, no preamble):
{{
  "shared_traits": [
    {{"trait": "short name", "evidence": "concrete span from the profiles", "weight": 8}}
  ],
  "career_patterns": ["short observed trajectory pattern"],
  "anti_signals": ["pattern absent across this group"],
  "summary": "2-4 sentences a recruiter can act on"
}}
""".strip()


def _parse_dna_json(raw: str) -> dict:
    """Parse + validate the model's trait JSON. Raises TeamDNAError on anything unusable."""
    if not raw or not raw.strip():
        raise TeamDNAError("The AI returned an empty response — nothing was saved.")

    text = raw.strip()
    # Strip a ```json fence if the model added one despite json_object mode.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("team_dna: unparseable JSON from model: %s", e)
        raise TeamDNAError(
            "The AI returned a response we couldn't read as JSON. Nothing was saved — please retry."
        )

    if not isinstance(data, dict):
        raise TeamDNAError("The AI returned an unexpected response shape. Nothing was saved.")

    traits, dropped = [], 0
    for item in data.get("shared_traits") or []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        name = (item.get("trait") or "").strip()
        evidence = (item.get("evidence") or "").strip()
        if not name or not evidence:
            dropped += 1                       # evidence rule: no evidence, no trait
            continue
        if _violates_guardrails(name, evidence):
            dropped += 1
            logger.info("team_dna: dropped trait failing bias guardrails: %r", name[:60])
            continue
        try:
            weight = max(1, min(10, int(item.get("weight", 5))))
        except (TypeError, ValueError):
            weight = 5
        traits.append({"trait": name[:120], "evidence": evidence[:400], "weight": weight})

    def _clean_list(key: str) -> List[str]:
        out = []
        for entry in data.get(key) or []:
            if isinstance(entry, str) and entry.strip() and not _violates_guardrails(entry):
                out.append(entry.strip()[:300])
        return out

    summary = (data.get("summary") or "").strip()
    if _violates_guardrails(summary):
        summary = ""

    if not traits:
        raise TeamDNAError(
            "No evidence-backed traits could be extracted from these profiles. "
            "Try fuller CVs, or profiles with more detail about what each person actually did."
        )

    result = {
        "shared_traits":   sorted(traits, key=lambda t: t["weight"], reverse=True),
        "career_patterns": _clean_list("career_patterns"),
        "anti_signals":    _clean_list("anti_signals"),
        "summary":         summary[:1200],
    }
    if dropped:
        result["traits_dropped"] = dropped
    return result


def fingerprint_profiles(profiles: List[dict]) -> str:
    """Stable hash of the profile set. Changes only when the set changes,
    which is exactly when the cached model must be rebuilt."""
    parts = sorted(
        f"{p.get('id') or ''}:{hashlib.sha256((p.get('raw_text') or '').encode('utf-8')).hexdigest()}"
        for p in profiles
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def extract_traits(profiles: List[dict]) -> dict:
    """Run the single GPT-4o extraction call over the exemplar profiles.

    One call for the whole set, as specified — the traits are about the GROUP,
    so the model has to see them together.
    """
    if len(profiles) < MIN_PROFILES:
        raise TeamDNAError(f"Team DNA needs at least {MIN_PROFILES} exemplar profiles.")
    if len(profiles) > MAX_PROFILES:
        raise TeamDNAError(f"Team DNA accepts at most {MAX_PROFILES} exemplar profiles.")

    start = time.time()
    try:
        client, model = get_openai_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content":
                    "You are a precise, bias-aware talent-pattern JSON engine. You extract only "
                    "job-relevant, evidence-backed patterns. You never infer protected "
                    "characteristics. You return JSON only."},
                {"role": "user", "content": build_dna_prompt(profiles)},
            ],
            temperature=0.2,
            max_tokens=1600,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        logger.warning("team_dna: AI backend unavailable: %s", e)
        raise TeamDNAError("The AI engine is temporarily unavailable — please retry in a moment.")

    parsed = _parse_dna_json(response.choices[0].message.content)
    parsed["_meta"] = {
        "model_used":    model,
        "latency_ms":    round((time.time() - start) * 1000, 2),
        "profile_count": len(profiles),
    }
    return parsed


def build_team_dna(user_id: str, role_id: str, db=None, company_id: str = None) -> dict:
    """Build (or return the cached) Team DNA model for a company + role.

    Cached in team_dna_models and rebuilt only when the profile set changes,
    tracked by source_fingerprint.

    Scoping: reads filter on company_id ONLY — Team DNA belongs to the company's
    team, so every colleague sees and contributes to the same model per role.
    user_id is recorded on the row for audit (who last built it) and is never
    used to scope a read.
    """
    if not company_id:
        raise TeamDNAError("company_id is required to build Team DNA.")
    from app.db import SessionLocal, TeamDNAProfileORM, TeamDNAModelORM

    owns_session = db is None
    db = db or SessionLocal()
    try:
        rows = db.query(TeamDNAProfileORM).filter(
            TeamDNAProfileORM.company_id == company_id,
            TeamDNAProfileORM.role_id == role_id,
            TeamDNAProfileORM.is_deleted == False,   # noqa: E712 - SQLAlchemy needs ==
        ).order_by(TeamDNAProfileORM.created_at.asc()).all()

        if len(rows) < MIN_PROFILES:
            raise TeamDNAError(
                f"Team DNA needs at least {MIN_PROFILES} exemplar profiles for this role "
                f"— you have {len(rows)}."
            )

        profiles = [{"id": r.id, "name": r.name, "raw_text": r.raw_text} for r in rows]
        fingerprint = fingerprint_profiles(profiles)

        cached = db.query(TeamDNAModelORM).filter(
            TeamDNAModelORM.company_id == company_id,
            TeamDNAModelORM.role_id == role_id,
        ).first()

        # Cache hit: same profile set, still-parseable payload.
        if cached and cached.source_fingerprint == fingerprint:
            try:
                return {**json.loads(cached.extracted_traits), "cached": True}
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("team_dna: cached payload corrupt for role=%s, rebuilding", role_id)

        extracted = extract_traits(profiles)
        meta = extracted.pop("_meta", {})
        payload = json.dumps(extracted)

        if cached:
            cached.user_id            = user_id      # audit: who last rebuilt it
            cached.extracted_traits   = payload
            cached.summary            = extracted.get("summary")
            cached.source_fingerprint = fingerprint
            cached.profile_count      = len(profiles)
            cached.model_used         = meta.get("model_used")
            cached.latency_ms         = meta.get("latency_ms")
        else:
            import uuid as _uuid
            db.add(TeamDNAModelORM(
                id=str(_uuid.uuid4()),
                company_id=company_id,
                user_id=user_id,
                role_id=role_id,
                extracted_traits=payload,
                summary=extracted.get("summary"),
                source_fingerprint=fingerprint,
                profile_count=len(profiles),
                model_used=meta.get("model_used"),
                latency_ms=meta.get("latency_ms"),
            ))
        db.commit()
        return {**extracted, "cached": False}
    finally:
        if owns_session:
            db.close()


# ============================================================
# FEEDBACK — calibration context, not retraining
# ============================================================

def feedback_context(db, company_id: str, user_id: str, role_id: str,
                     limit: int = MAX_FEEDBACK_EXAMPLES) -> str:
    """Render the team's last N verdicts on this role as prompt context.

    Company-scoped: a colleague's verdicts calibrate your scoring too, which is
    the point of a shared Team DNA. user_id is accepted for signature symmetry
    and audit, not used to filter.

    Deliberately prompt-only: no retraining, no weights, nothing persisted
    beyond the rows the team can see and delete.
    """
    from app.db import CandidateFeedbackORM

    rows = (
        db.query(CandidateFeedbackORM)
        .filter(
            CandidateFeedbackORM.company_id == company_id,
            CandidateFeedbackORM.role_id == role_id,
        )
        .order_by(CandidateFeedbackORM.created_at.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return ""

    lines = []
    for r in rows:
        who = (r.candidate_name or "a candidate").strip()
        reason = (r.reason or "").strip()
        verdict = "ACCEPTED" if r.verdict == "good" else "REJECTED"
        lines.append(f"- {verdict}: {who}" + (f" — because: {reason}" if reason else ""))

    return (
        "RECRUITER CALIBRATION — this hiring team's past verdicts on this role:\n"
        + "\n".join(lines)
        + "\n\nTreat these as calibration for this team's bar, not as rules. "
        "Reasons that reference protected characteristics must be IGNORED entirely."
    )
