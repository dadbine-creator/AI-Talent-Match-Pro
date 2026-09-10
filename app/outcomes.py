# outcomes.py
# ============================================================
# AI Talent Match Pro — hiring outcome tracking
#
# Pairs the score a candidate was given with what actually happened to them.
# The value of this dataset is entirely in its honesty, so two rules are
# enforced here rather than left to the caller:
#
#   1. A band's percentages are suppressed below MIN_BAND_SAMPLE candidates.
#      A "67% hire rate" from 3 people is noise wearing a suit, and once it is
#      on a screen someone will quote it.
#   2. Nothing is extrapolated, projected or smoothed. Every number returned
#      is a count of rows that exist, or a ratio of two such counts.
# ============================================================
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

# Ordered funnel. Position matters: "reached interview" means furthest_stage
# sits at INTERVIEWED or beyond.
STAGE_ORDER = ["sourced", "contacted", "screened", "interviewed", "offered", "hired"]

# Terminal outcomes. They can be entered from any stage and do not advance the
# funnel — a candidate rejected after an interview keeps furthest_stage
# "interviewed".
TERMINAL_STAGES = ["rejected", "withdrawn"]

VALID_STAGES = STAGE_ORDER + TERMINAL_STAGES

# Below this many candidates a band reports insufficient_data instead of
# percentages. Five is low for statistical comfort but it is what the spec
# asks for; the point is that it is a floor, not a claim of significance.
MIN_BAND_SAMPLE = 5

# Retention follow-up window.
RETENTION_FOLLOW_UP_DAYS = 365

SCORE_BANDS = [
    {"key": "90_100",  "label": "90-100",  "min": 90.0, "max": 100.01},
    {"key": "80_89",   "label": "80-89",   "min": 80.0, "max": 90.0},
    {"key": "70_79",   "label": "70-79",   "min": 70.0, "max": 80.0},
    {"key": "below_70", "label": "Below 70", "min": -0.01, "max": 70.0},
]


def stage_rank(stage: str) -> int:
    """Position in the funnel. Terminal stages return -1 (they are not a rung)."""
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def advance_furthest(current_furthest: str, new_stage: str) -> str:
    """The furthest rung reached, never going backwards.

    A rejection does not erase the fact that someone got to interview — that
    is precisely the data the funnel needs.
    """
    if new_stage in TERMINAL_STAGES:
        return current_furthest or "sourced"
    new_rank = stage_rank(new_stage)
    old_rank = stage_rank(current_furthest or "sourced")
    return new_stage if new_rank > old_rank else (current_furthest or "sourced")


def band_for_score(score: Optional[float]) -> Optional[str]:
    """Which score band a value falls in. None for unscored candidates —
    they are excluded from band stats rather than lumped into 'below 70'."""
    if score is None:
        return None
    for band in SCORE_BANDS:
        if band["min"] <= float(score) < band["max"]:
            return band["key"]
    return None


def follow_up_due(row) -> bool:
    """True when a hired candidate is due their 12-month retention check."""
    if row.stage != "hired" or not row.hired_at:
        return False
    if row.still_employed is not None:
        return False                       # already answered
    return datetime.utcnow() >= row.hired_at + timedelta(days=RETENTION_FOLLOW_UP_DAYS)


def follow_up_date(row) -> Optional[str]:
    if row.stage != "hired" or not row.hired_at:
        return None
    return (row.hired_at + timedelta(days=RETENTION_FOLLOW_UP_DAYS)).date().isoformat()


def _pct(numerator: int, denominator: int) -> Optional[float]:
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)


def compute_band_stats(rows: List) -> dict:
    """Aggregate outcomes into score bands.

    Returns one entry per band. A band with fewer than MIN_BAND_SAMPLE
    candidates reports insufficient_data and carries NO percentages at all —
    not even a hidden one — so there is nothing for a caller to accidentally
    render.
    """
    buckets = {band["key"]: [] for band in SCORE_BANDS}
    unscored = 0

    for row in rows:
        key = band_for_score(row.score_at_time)
        if key is None:
            unscored += 1
            continue
        buckets[key].append(row)

    bands = []
    for band in SCORE_BANDS:
        group = buckets[band["key"]]
        total = len(group)

        entry = {
            "band": band["key"],
            "label": band["label"],
            "candidates": total,
            "min_sample": MIN_BAND_SAMPLE,
        }

        if total < MIN_BAND_SAMPLE:
            # Deliberately no percentages, not even zeros — an absent key
            # cannot be misread as a measurement.
            entry["insufficient_data"] = True
            entry["message"] = (
                f"Not enough data yet — {total} of {MIN_BAND_SAMPLE} candidates needed."
            )
            bands.append(entry)
            continue

        reached_interview = sum(
            1 for r in group if stage_rank(r.furthest_stage) >= stage_rank("interviewed")
        )
        hired = sum(1 for r in group if stage_rank(r.furthest_stage) >= stage_rank("hired"))

        # Retention is a ratio of ANSWERED checks only. Counting unanswered
        # follow-ups as "still employed" would inflate it, and counting them as
        # departures would deflate it; both are inventions.
        checked = [r for r in group if r.still_employed is not None]
        still_employed = sum(1 for r in checked if r.still_employed)

        entry.update({
            "insufficient_data": False,
            "reached_interview": reached_interview,
            "reached_interview_pct": _pct(reached_interview, total),
            "hired": hired,
            "hired_pct": _pct(hired, total),
            "retention_checked": len(checked),
            "still_employed": still_employed,
            "still_employed_pct": _pct(still_employed, len(checked)),
        })
        if not checked:
            entry["still_employed_pct"] = None
            entry["retention_note"] = "No 12-month checks answered yet."
        bands.append(entry)

    return {
        "bands": bands,
        "total_outcomes": len(rows),
        "unscored_outcomes": unscored,
        "min_band_sample": MIN_BAND_SAMPLE,
        # Stated in the payload so any consumer of this API inherits the rule.
        "disclaimer": (
            "Counts are of recorded outcomes only. Bands with fewer than "
            f"{MIN_BAND_SAMPLE} candidates report no percentages. Nothing here is "
            "projected or extrapolated."
        ),
    }


def outcome_context(db, company_id: str, role_id: str, limit: int = 20) -> str:
    """Render recorded outcomes as calibration context for Team DNA scoring.

    A real hire is a far stronger signal than a thumbs-up: someone backed it
    with a job. The prompt says so explicitly rather than leaving the model to
    guess the weighting.

    Returns "" when there is nothing recorded — never a fabricated summary.
    """
    from app.db import CandidateOutcomeORM

    rows = (
        db.query(CandidateOutcomeORM)
        .filter(
            CandidateOutcomeORM.company_id == company_id,
            CandidateOutcomeORM.role_id == role_id,
        )
        .order_by(CandidateOutcomeORM.updated_at.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return ""

    strong, weak = [], []
    for r in rows:
        score = f" (scored {int(r.score_at_time)})" if r.score_at_time is not None else ""
        if r.furthest_stage == "hired":
            retention = ""
            if r.still_employed is True:
                retention = ", still employed at the 12-month check"
            elif r.still_employed is False:
                retention = ", but had left by the 12-month check"
            strong.append(f"- HIRED{score}{retention}")
        elif r.stage == "rejected":
            reason = f" — reason: {r.rejected_reason.strip()}" if r.rejected_reason else ""
            weak.append(f"- REJECTED at {r.furthest_stage}{score}{reason}")
        elif r.stage == "withdrawn":
            weak.append(f"- WITHDREW at {r.furthest_stage}{score}")

    if not strong and not weak:
        return ""

    parts = ["REAL HIRING OUTCOMES for this role — the strongest calibration available."]
    parts.append(
        "A candidate who was actually HIRED is a much stronger positive signal than a "
        "thumbs-up: someone committed a job to that judgement. Weight these well above "
        "the recruiter verdicts above. A rejection late in the funnel (after interview) "
        "is a stronger negative than an early one."
    )
    if strong:
        parts.append("Hired:\n" + "\n".join(strong))
    if weak:
        parts.append("Did not convert:\n" + "\n".join(weak))
    parts.append(
        "Treat these as calibration for this team's real bar, not as rules, and IGNORE "
        "entirely any reason that references protected characteristics."
    )
    return "\n\n".join(parts)
