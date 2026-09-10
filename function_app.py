"""
============================================================
AI Talent Match Pro — Azure Function App
Phase 20 — Serverless API Endpoint
Enhanced with:
  1. Pydantic schema validation
  2. Structured logging
  3. Version header
  4. Cold-start metric
  5. Max payload guard
============================================================
"""

import azure.functions as func
import json
import logging
import os
import time
from pydantic import BaseModel, ValidationError
from ai_engine import run_full_talent_match

# ── Logging ──────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ── Cold start tracking ───────────────────────────────────
# Enhancement 4 — track Azure cold starts
COLD_START = os.environ.get("COLD_START", "true")
os.environ["COLD_START"] = "false"

# ── Version ───────────────────────────────────────────────
API_VERSION = "20.0.0"

# =============================================================
# 1. PYDANTIC SCHEMA VALIDATION
# Enhancement 1 — enterprise-grade request validation
# =============================================================
class JobRequest(BaseModel):
    title: str
    description: str = ""
    required_skills: list[str] = []
    seniority: str = "Mid-Senior"
    location: str = ""

class CandidateRequest(BaseModel):
    name: str
    title: str = ""
    skills: list[str] = []
    years_experience: int = 0
    location: str = ""
    career_history: list[str] = []

class GradeRequest(BaseModel):
    job: JobRequest
    candidates: list[CandidateRequest]
    membership_tier: str = "free"

# ── Azure Function App ────────────────────────────────────
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# =============================================================
# 2. GRADE ENDPOINT
# =============================================================
@app.route(route="grade", methods=["POST"])
def grade_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """
    POST /api/grade
    Grades candidates against a job description.
    Returns multi-dimensional scores in <100ms.
    """
    start_time = time.time()

    # ── CORS + Version Headers ────────────────────────────
    # Enhancement 3 — version header
    headers = {
        "Content-Type":                "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, x-functions-key",
        "X-ATM-Version":               API_VERSION  # ← Enhancement 3
    }

    # ── Handle OPTIONS preflight ──────────────────────────
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=200, headers=headers)

    try:
        # ── Parse body ────────────────────────────────────
        body = req.get_json()

        if not body:
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Request body is required"}),
                status_code=400,
                headers=headers
            )

        # ── Enhancement 1 — Pydantic validation ──────────
        try:
            grade_request = GradeRequest(**body)
        except ValidationError as e:
            logger.error(json.dumps({
                "event": "validation_error",
                "errors": e.errors()
            }))
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Invalid request format", "details": e.errors()}),
                status_code=400,
                headers=headers
            )

        candidates = grade_request.candidates
        job        = grade_request.job
        tier       = grade_request.membership_tier

        # ── Enhancement 5 — Max payload guard ────────────
        if len(candidates) > 50:
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Too many candidates (max 50)"}),
                status_code=400,
                headers=headers
            )

        # ── Enhancement 2 — Structured logging ───────────
        logger.info(json.dumps({
            "event":           "grading_started",
            "job_title":       job.title,
            "candidate_count": len(candidates),
            "membership_tier": tier,
            "cold_start":      COLD_START == "true"
        }))

        # ── Run AIGradeEngine ─────────────────────────────
        results = run_full_talent_match(
            role_title=job.title,
            human_story=job.description,
            membership_tier=tier
        )

        # ── Calculate latency ─────────────────────────────
        latency_ms = int((time.time() - start_time) * 1000)

        # ── Enhancement 2 — Structured logging ───────────
        logger.info(json.dumps({
            "event":      "grading_completed",
            "job_title":  job.title,
            "latency_ms": latency_ms,
            "count":      len(results),
            "cold_start": COLD_START == "true"
        }))

        # ── Return response ───────────────────────────────
        return func.HttpResponse(
            json.dumps({
                "success":    True,
                "version":    API_VERSION,
                "latency_ms": latency_ms,
                "cold_start": COLD_START == "true",   # Enhancement 4
                "job_title":  job.title,
                "count":      len(results),
                "results":    results
            }),
            status_code=200,
            headers=headers
        )

    except ValueError:
        return func.HttpResponse(
            json.dumps({"success": False, "error": "Invalid JSON in request body"}),
            status_code=400,
            headers=headers
        )

    except Exception as e:
        logger.error(json.dumps({
            "event": "grading_error",
            "error": str(e)
        }))
        return func.HttpResponse(
            json.dumps({"success": False, "error": "Internal server error"}),
            status_code=500,
            headers=headers
        )


# =============================================================
# 3. HEALTH ENDPOINT
# =============================================================
@app.route(route="health", methods=["GET"])
def health_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """
    GET /api/health
    Health check for Azure Monitor + LinkedIn integration.
    """
    return func.HttpResponse(
        json.dumps({
            "status":     "healthy",
            "service":    "AI Talent Match Pro — AIGradeEngine",
            "version":    API_VERSION,
            "cold_start": COLD_START == "true"
        }),
        status_code=200,
        headers={
            "Content-Type": "application/json",
            "X-ATM-Version": API_VERSION
        }
    )