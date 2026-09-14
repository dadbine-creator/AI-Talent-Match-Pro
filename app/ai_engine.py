# ai_engine.py
# ============================================================
# AI Talent Match Pro — Deep Thinking Engine
# Phase 20 Upgrade:
#   + adaptability score
#   + focus_penalty score
#   + Azure OpenAI support (falls back to OpenAI)
#   + CosmosDB storage
#   + Batch scoring against Team DNA
# ============================================================

import json
import os
import time
import logging
from typing import List, Literal, TypedDict, Optional
from openai import OpenAI, AzureOpenAI

# ── Logging ──────────────────────────────────────────────
logger = logging.getLogger(__name__)

# =============================================================
# 1. DATA SCHEMAS
# =============================================================
Tier = Literal["gold", "silver", "bronze"]

class CandidateResult(TypedDict):
    name: str
    tier: Tier
    match_score: int
    adaptability: int        # Phase 20 — new
    focus_penalty: int       # Phase 20 — new
    ai_analysis: str
    silent_skill: Optional[str]
    boolean_search: Optional[str]
    linkedin_url: Optional[str]
    profile_pic: Optional[str]
    experience_summary: Optional[str]
    latency_ms: Optional[int]  # Phase 20 — new

# =============================================================
# 2. OPENAI CLIENT FACTORY
# Phase 20: Prefers Azure OpenAI, falls back to OpenAI
# =============================================================
def get_openai_client():
    """
    Returns Azure OpenAI client if Azure env vars are set,
    otherwise falls back to standard OpenAI client.
    """
    azure_key      = os.getenv("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

    if azure_key and azure_endpoint:
        logger.info("Using Azure OpenAI client")
        return AzureOpenAI(
            api_key=azure_key,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            azure_endpoint=azure_endpoint
        ), os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
    else:
        logger.info("Using standard OpenAI client")
        return OpenAI(api_key=os.getenv("OPENAI_API_KEY")), "gpt-4o"

# =============================================================
# 3. THE LEGS (LinkedIn Search Engine Stub)
# =============================================================
def search_linkedin_profiles(search_query: dict) -> List[dict]:
    """
    Placeholder for LinkedIn Partner API.
    In Phase 21, this receives the boolean string and calls
    the real LinkedIn Talent Solutions API.
    """
    return [
        {
            "name": "Alex Rivier",
            "linkedin_url": "https://linkedin.com/in/alex-rivier",
            "profile_pic": None,
            "experience_summary": "10 years in product leadership roles across SaaS and AI.",
        },
        {
            "name": "Jordan Smith",
            "linkedin_url": "https://linkedin.com/in/jordan-smith",
            "profile_pic": None,
            "experience_summary": "Strong PM background with cross-functional experience.",
        },
        {
            "name": "Taylor Wong",
            "linkedin_url": "https://linkedin.com/in/taylor-wong",
            "profile_pic": None,
            "experience_summary": "Solid contributor with relevant domain exposure.",
        }
    ]

# =============================================================
# 4. THE BRAIN (Phase 20 Upgraded 5-Layer Deep-Thinking Prompt)
# =============================================================
def build_deep_thinking_prompt(role_title: str, human_story: str, membership_tier: str) -> str:
    """
    Phase 20 upgrade: adds adaptability + focus_penalty to output.
    membership_tier: free, business, corporate
    """
    tier_rules = {
        "free":      "Return ONLY 1 candidate. Keep analysis short.",
        "business":  "Return EXACTLY 2 candidates. Include boolean search.",
        "corporate": "Return EXACTLY 3 candidates. Include boolean search + silent skills + trajectory logic."
    }

    return f"""
You are the Silent Skill Deep-Thinking Engine for a product called "AI Talent Match Pro."

Your job is to read a hiring manager's Human Story and transform it into a structured,
intelligent talent-matching output. You must think in layers and return ONLY structured JSON.

============================================================
MEMBERSHIP TIER RULES
============================================================
User Tier: {membership_tier}
{tier_rules[membership_tier]}

============================================================
LAYER 1 — ROLE UNDERSTANDING
============================================================
Interpret the role title deeply:
- Identify the true business need and environment (chaotic, scaling, founder-led, etc.).
- Identify industry context (SaaS, AI, fintech, healthcare, etc.).

============================================================
LAYER 2 — SILENT SKILLS (PSYCHOLOGICAL LAYER)
============================================================
Identify 1 Silent Skill per candidate (e.g., "Creates clarity in chaos").
Each candidate MUST have one Silent Skill.

============================================================
LAYER 3 — LINKEDIN SEARCH STRATEGY
============================================================
Generate:
- keywords
- seniority levels
- boolean search string

============================================================
LAYER 4 — CANDIDATE SCORING LOGIC (STRICT RULES)
============================================================
You MUST follow these exact rules:
1. Assign EXACTLY one tier: gold (95–100), silver (85–94), bronze (70–84).
2. You MUST return a match_score that fits the tier range.
3. TRAJECTORY BONUS RULE:
   - If the career path makes this role their "next logical step," add +5 to match_score.
   - You MUST explicitly mention the Trajectory Bonus in the ai_analysis.
   - The final score MUST still fall within the tier range.
4. Include exactly one Silent Skill for each candidate.
5. Include industry alignment in scoring.
6. Include experience weighting (seniority, years, domain relevance).

============================================================
LAYER 4B — PHASE 20 SCORING (NEW — REQUIRED)
============================================================
For each candidate, also score:

- adaptability (0-100):
  How well can this candidate transfer their skills across roles or industries?
  100 = highly adaptable generalist. 0 = very narrow specialist.

- focus_penalty (0-100):
  How scattered is their career history?
  0 = highly focused, linear career. 100 = very scattered, many unrelated roles.
  A high focus_penalty REDUCES confidence in the match.

These two scores are REQUIRED in the output JSON for every candidate.

============================================================
LAYER 5 — NARRATIVE ANALYSIS
============================================================
Write a warm, human explanation including:
- Silent Skill
- Trajectory logic
- Industry alignment
- Experience weighting
- Brief mention of adaptability and focus

Keep the narrative concise, warm, and no longer than 4 sentences.

============================================================
OUTPUT FORMAT (STRICT JSON OBJECT)
============================================================
Return ONLY this JSON structure — no markdown, no preamble:
{{
  "search_strategy": {{ "keywords": [], "seniority": [], "boolean": "" }},
  "candidates": [
    {{
      "name": "Candidate Name",
      "tier": "gold",
      "match_score": 98,
      "adaptability": 85,
      "focus_penalty": 10,
      "silent_skill": "Creates clarity in chaos",
      "ai_analysis": "Narrative...",
      "boolean_search": "string"
    }}
  ]
}}

ROLE TITLE: {role_title}
HUMAN STORY: {human_story}
""".strip()

# =============================================================
# 5. THE ORCHESTRATOR (Phase 20 Upgraded)
# =============================================================
def run_full_talent_match(
    role_title: str,
    human_story: str,
    membership_tier: str = "free"
) -> List[CandidateResult]:

    start_time = time.time()

    # A. Initial Fetch (Legs)
    raw_profiles = search_linkedin_profiles({"keywords": role_title})
    if not raw_profiles:
        return []

    # B. Generate Prompt
    prompt = build_deep_thinking_prompt(role_title, human_story, membership_tier)

    # C. Get client (Azure or standard OpenAI)
    client, model = get_openai_client()

    # D. Call OpenAI
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a professional talent intelligence JSON engine."},
                {"role": "user",   "content": prompt}
            ],
            temperature=0.3,
            max_tokens=800,
            response_format={"type": "json_object"}
        )
    except Exception as e:
        logger.error(f"OpenAI call failed: {e}")
        return []

    # E. Parse JSON
    try:
        raw_content = response.choices[0].message.content
        data = json.loads(raw_content)
        evaluations     = data.get("candidates", [])
        search_strategy = data.get("search_strategy", {})
    except Exception as e:
        logger.error(f"Failed to parse AI response: {e}")
        return []

    # F. Membership Tier Limits
    tier_limits = {"free": 1, "business": 2, "corporate": 3}
    limit = tier_limits.get(membership_tier, 1)

    # G. Calculate latency
    latency_ms = int((time.time() - start_time) * 1000)
    logger.info(f"Talent match completed in {latency_ms}ms")

    # H. Final Merge
    final_matches: List[CandidateResult] = []

    for i in range(min(limit, len(evaluations), len(raw_profiles))):
        eval_item    = evaluations[i]
        profile_item = raw_profiles[i]

        final_matches.append({
            "name":               profile_item["name"],
            "tier":               eval_item.get("tier", "bronze"),
            "match_score":        int(eval_item.get("match_score", 70)),
            "adaptability":       int(eval_item.get("adaptability", 60)),   # Phase 20
            "focus_penalty":      int(eval_item.get("focus_penalty", 20)),  # Phase 20
            "ai_analysis":        eval_item.get("ai_analysis", ""),
            "silent_skill":       eval_item.get("silent_skill", None),
            "boolean_search":     search_strategy.get("boolean", None),
            "linkedin_url":       profile_item["linkedin_url"],
            "profile_pic":        profile_item["profile_pic"],
            "experience_summary": profile_item["experience_summary"],
            "latency_ms":         latency_ms                                # Phase 20
        })

    return final_matches


# =============================================================
# 6. REAL CANDIDATE SCORING (no Apollo needed)
# Scores candidates the recruiter actually provides (pasted résumés /
# LinkedIn summaries) against a job description. Unlike the stub
# sourcing above, this feeds each real candidate's text to GPT-4o and
# scores THAT person — no invented profiles.
# =============================================================
def build_candidate_scoring_prompt(role_title: str, job_description: str, roster: str, n: int) -> str:
    return f"""
You are the Silent Skill Deep-Thinking Engine for "AI Talent Match Pro."

Score the {n} candidate(s) below against the role. Evaluate ONLY these candidates —
never invent or add candidates. Return them in the SAME order given.

ROLE TITLE: {role_title}

JOB DESCRIPTION / HIRING MANAGER STORY:
{job_description}

CANDIDATES:
{roster}

For EACH candidate return:
- tier: "gold" (95-100), "silver" (85-94), or "bronze" (70-84)
- match_score: integer within the tier range
- adaptability: 0-100 (skill transfer across roles/industries)
- focus_penalty: 0-100 (0 = linear focused career, 100 = scattered)
- silent_skill: one non-obvious strength inferred from their background
- ai_analysis: 2-4 warm, specific sentences citing details from THIS candidate's text
- evidence: an object with short, concrete justifications drawn from the candidate's text:
    {{ "role_fit": "...", "experience": "...", "adaptability": "...", "focus": "..." }}

Base every score and justification on evidence in the candidate's own text. If a candidate's
text is thin, score conservatively and say so — do not fabricate experience.

Return ONLY this JSON (no markdown, no preamble):
{{
  "search_strategy": {{ "keywords": [], "seniority": [] }},
  "candidates": [
    {{
      "name": "echo the candidate's given name",
      "tier": "gold",
      "match_score": 96,
      "adaptability": 88,
      "focus_penalty": 12,
      "silent_skill": "Creates clarity in chaos",
      "ai_analysis": "…",
      "evidence": {{ "role_fit": "…", "experience": "…", "adaptability": "…", "focus": "…" }}
    }}
  ]
}}
""".strip()


def score_candidates(
    role_title: str,
    job_description: str,
    candidates: List[dict],
    membership_tier: str = "free",
):
    """
    Score REAL provided candidates against a job description with GPT-4o.

    candidates: list of {"name": str, "text": str, "linkedin_url": Optional[str]}.
    Returns (results, search_strategy).

    Raises on AI/parse failure so the caller surfaces an honest error instead of
    fabricating scores. Requires a working AI backend (Azure OpenAI in prod).
    """
    if not candidates:
        return [], {}

    start_time = time.time()
    client, model = get_openai_client()

    roster = "\n\n".join(
        f"[Candidate {i+1}] {(c.get('name') or f'Candidate {i+1}')}\n{(c.get('text') or '').strip()[:4000]}"
        for i, c in enumerate(candidates)
    )
    prompt = build_candidate_scoring_prompt(role_title, job_description, roster, len(candidates))

    # Raises on failure (no key / network / API error) — intentional; caller returns a clean error.
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a precise talent-evaluation JSON engine. Score ONLY the candidates provided; never invent candidates."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1800,
        response_format={"type": "json_object"},
    )

    data = json.loads(response.choices[0].message.content)
    evals = data.get("candidates", [])
    search_strategy = data.get("search_strategy", {})
    latency_ms = int((time.time() - start_time) * 1000)

    def _clamp(v, lo, hi, default):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return default

    results: List[dict] = []
    for i, cand in enumerate(candidates):
        ev = evals[i] if i < len(evals) else {}
        results.append({
            "name":               cand.get("name") or f"Candidate {i+1}",
            "tier":               ev.get("tier", "bronze") if ev.get("tier") in ("gold", "silver", "bronze") else "bronze",
            "match_score":        _clamp(ev.get("match_score", 70), 0, 100, 70),
            "adaptability":       _clamp(ev.get("adaptability", 60), 0, 100, 60),
            "focus_penalty":      _clamp(ev.get("focus_penalty", 20), 0, 100, 20),
            "ai_analysis":        ev.get("ai_analysis", ""),
            "silent_skill":       ev.get("silent_skill"),
            "evidence":           ev.get("evidence", {}),
            "boolean_search":     None,
            "linkedin_url":       cand.get("linkedin_url"),
            "profile_pic":        None,
            "experience_summary": ((cand.get("text") or "")[:200] or None),
            "latency_ms":         latency_ms,
        })

    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results, search_strategy

# =============================================================
# 6. TEAM DNA SCORING  (additive — score_candidates above is untouched)
#
# Scores ONE candidate against the company's own Team DNA model instead of
# against a pasted job description. Returns the same shape /api/candidates/score
# already returns, so the existing gold/silver/bronze card renders it with no
# frontend change, plus one extra field: dna_matches.
# =============================================================

def build_team_dna_scoring_prompt(
    candidate_text: str,
    team_dna_model: dict,
    job_description: str = None,
    calibration: str = "",
) -> str:
    """Prompt for scoring a candidate against an extracted Team DNA model."""
    traits = team_dna_model.get("shared_traits") or []
    trait_lines = "\n".join(
        f"- {t.get('trait')} (weight {t.get('weight', 5)}/10) — seen in the team as: {t.get('evidence', '')}"
        for t in traits
    ) or "- (no traits extracted)"

    patterns = "\n".join(f"- {p}" for p in (team_dna_model.get("career_patterns") or [])) or "- (none)"
    anti = "\n".join(f"- {a}" for a in (team_dna_model.get("anti_signals") or [])) or "- (none)"

    jd_block = ""
    if job_description and job_description.strip():
        jd_block = (
            "\nSECONDARY CONTEXT — the open role's job description. The Team DNA above "
            "is the PRIMARY standard; use this only to break ties:\n"
            f"{job_description.strip()[:3000]}\n"
        )

    calibration_block = f"\n{calibration}\n" if calibration else ""

    return f"""
You are the Team DNA scoring engine for "AI Talent Match Pro."

Score ONE candidate against the profile of people who ALREADY SUCCEED at this
company. You are not matching keywords against a job ad — you are asking
"does this person share what makes this specific team good?"

TEAM DNA — shared traits of the company's best people:
{trait_lines}

CAREER PATTERNS in this team:
{patterns}

ANTI-SIGNALS (patterns absent from this team — context only, NOT rejection rules):
{anti}
{jd_block}{calibration_block}
CANDIDATE:
{(candidate_text or '').strip()[:8000]}

HARD CONSTRAINTS — these override every other instruction:
NEVER use, infer or mention age, gender, ethnicity, nationality, citizenship,
visa status, religion, school prestige, name origin, appearance, personality
type, marital/family status, health or disability. Judge only demonstrated
skills, scope of ownership, career trajectory, problem domains and technical
depth. If the candidate's text is thin, score conservatively and SAY SO rather
than inventing experience.

Weight each matched trait by its weight. A candidate matching two 9-weight
traits beats one matching five 2-weight traits.

For dna_matches, return one entry for EVERY trait listed above, in the same
order, with found=true only when concrete evidence exists in the candidate's
own text. When found=false, evidence must say what is missing.

Return ONLY this JSON (no markdown, no preamble):
{{
  "tier": "gold" | "silver" | "bronze",
  "match_score": 0-100,
  "adaptability": 0-100,
  "focus_penalty": 0-100,
  "silent_skill": "one non-obvious strength inferred from their background",
  "ai_analysis": "2-4 specific sentences citing THIS candidate's text and naming which team traits they share",
  "dna_matches": [
    {{"trait": "echo the trait name", "found": true, "evidence": "concrete span from the candidate's text"}}
  ]
}}

Tier bands: gold 95-100, silver 85-94, bronze 70-84. match_score must sit inside
the band you choose.
""".strip()


def score_against_team_dna(
    candidate_text: str,
    team_dna_model: dict,
    job_description: str = None,
    candidate_name: str = None,
    calibration: str = "",
):
    """Score one candidate against a Team DNA model.

    Returns the same dict shape as score_candidates() entries (so the existing
    candidate card renders it unchanged) plus "dna_matches".

    Raises on AI/parse failure so the caller surfaces an honest error — there is
    no fallback score.
    """
    if not (candidate_text or "").strip():
        raise ValueError("candidate_text is required")
    if not team_dna_model or not team_dna_model.get("shared_traits"):
        raise ValueError("team_dna_model must contain shared_traits")

    start_time = time.time()
    client, model = get_openai_client()

    prompt = build_team_dna_scoring_prompt(
        candidate_text, team_dna_model, job_description, calibration
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content":
                "You are a precise, bias-aware talent-evaluation JSON engine. You score the ONE "
                "candidate provided against a team profile. You never infer protected "
                "characteristics. You return JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1400,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    try:
        ev = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        # Honest failure — never fabricate a score.
        raise ValueError("The AI returned an unreadable response — no score was produced.")
    if not isinstance(ev, dict):
        raise ValueError("The AI returned an unexpected response shape — no score was produced.")

    latency_ms = int((time.time() - start_time) * 1000)

    def _clamp(v, lo, hi, default):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return default

    tier = ev.get("tier") if ev.get("tier") in ("gold", "silver", "bronze") else "bronze"

    # Keep only traits the model was actually asked about, and drop any evidence
    # that trips the bias guardrails rather than showing it to the recruiter.
    from app.team_dna import _violates_guardrails
    known = {t.get("trait") for t in (team_dna_model.get("shared_traits") or [])}
    dna_matches = []
    for m in (ev.get("dna_matches") or []):
        if not isinstance(m, dict):
            continue
        name = (m.get("trait") or "").strip()
        if name not in known:
            continue
        evidence = (m.get("evidence") or "").strip()
        if _violates_guardrails(name, evidence):
            continue
        dna_matches.append({
            "trait":    name[:120],
            "found":    bool(m.get("found")),
            "evidence": evidence[:400],
        })

    analysis = (ev.get("ai_analysis") or "").strip()
    silent_skill = (ev.get("silent_skill") or "").strip() or None
    if _violates_guardrails(analysis):
        analysis = "Scored against your team's profile. Some model output was withheld because it referenced characteristics we don't evaluate on."
    if silent_skill and _violates_guardrails(silent_skill):
        silent_skill = None

    return {
        "name":               candidate_name or "Candidate",
        "tier":               tier,
        "match_score":        _clamp(ev.get("match_score", 70), 0, 100, 70),
        "adaptability":       _clamp(ev.get("adaptability", 60), 0, 100, 60),
        "focus_penalty":      _clamp(ev.get("focus_penalty", 20), 0, 100, 20),
        "ai_analysis":        analysis,
        "silent_skill":       silent_skill,
        "dna_matches":        dna_matches,
        "evidence":           {},
        "boolean_search":     None,
        "linkedin_url":       None,
        "profile_pic":        None,
        "experience_summary": ((candidate_text or "")[:200] or None),
        "latency_ms":         latency_ms,
        "scored_against":     "team_dna",
    }
