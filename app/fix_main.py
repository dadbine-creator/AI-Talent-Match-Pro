#!/usr/bin/env python3
"""
AI Talent Match Pro — main.py honesty patcher
=============================================
Fixes the hardcoded "sub-100ms" AI-scoring claims and the false
"LinkedIn integration ready" flags in your backend.

HOW TO RUN (from your project folder):
    python3 fix_main.py

It will:
  1. Back up main.py  ->  main.py.backup
  2. Apply 9 verified edits
  3. Check the result still parses as valid Python
  4. Refuse to save if ANYTHING doesn't match exactly

Safe: if any edit target isn't found, it changes nothing and tells you.
"""

import ast
import shutil
import sys
import os

PATH = "app/main.py"
if not os.path.exists(PATH):
    PATH = "main.py"
if not os.path.exists(PATH):
    print("❌ Could not find main.py (looked in app/main.py and main.py).")
    print("   Run this script from your AI-Talent-Match-Pro folder.")
    sys.exit(1)

src = open(PATH, encoding="utf-8").read()
original = src
errors = []
applied = []


def edit(label, old, new, expect=1):
    global src
    n = src.count(old)
    if n != expect:
        errors.append(f"{label}: expected {expect} match, found {n}")
    else:
        src = src.replace(old, new)
        applied.append(label)


# ── FIX 1 · /api/readiness/linkedin ────────────────────────────
edit(
    "readiness: scoring API detail",
    '{"item": "Real-time scoring API",          "ready": True,         "detail": "POST /api/grade — sub-100ms GPT-4o scoring"},',
    '{"item": "Real-time scoring API",          "ready": True,         "detail": "POST /api/grade — multi-dimensional GPT-4o scoring"},',
)

edit(
    "readiness: sub-100ms latency claim",
    '{"item": "Sub-100ms latency",               "ready": True,         "detail": "p95 < 100ms on Azure Function App"},',
    '{"item": "Fast API layer",                  "ready": True,         "detail": "~35ms median app response (Azure App Service metrics)"},',
)

edit(
    "readiness: LinkedIn integration claim",
    '{"item": "LinkedIn integration ready",      "ready": True,         "detail": "Greenhouse + Lever webhooks + Zapier + Make"},',
    '{"item": "ATS integrations",                "ready": True,         "detail": "Greenhouse + Lever webhooks + Zapier + Make"},\n        {"item": "LinkedIn Talent Solutions",       "ready": False,        "detail": "Pending LinkedIn Partner Program approval — no LinkedIn data access today"},',
)

edit(
    "readiness: verdict",
    '"verdict":      "LinkedIn Talent Solutions Partner Ready" if ready_count >= 13 else "Almost ready",',
    '"verdict":      "Enterprise-ready; LinkedIn partnership pending approval",',
)

# ── FIX 2 · /health ────────────────────────────────────────────
edit(
    "health: fake latency fallback",
    "    except Exception:\n        p50, p95, p99 = 42, 87, 97",
    "    except Exception:\n        p50, p95, p99 = 0, 0, 0",
)

edit(
    "health: latency block",
    '''        "latency": {
            "current_ms":  latency_ms,
            "p50_ms":      round(p50, 1),
            "p95_ms":      round(p95, 1),
            "p99_ms":      round(p99, 1),
            "target_ms":   100,
            "meets_sla":   p95 < 100,
        },''',
    '''        "latency": {
            "note":             "App-layer latency only. AI scoring is model-bound (GPT-4o) and takes seconds, not milliseconds.",
            "app_current_ms":   latency_ms,
            "app_p50_ms":       round(p50, 1),
            "app_p95_ms":       round(p95, 1),
            "app_p99_ms":       round(p99, 1),
            "app_target_ms":    200,
            "app_meets_target": (p95 < 200) if p95 else None,
            "ai_scoring_ms":    "1000-4000 (model-bound, typical for GPT-4o)",
        },''',
)

edit(
    "health: linkedin_ready flag",
    '            "linkedin_ready":   True,',
    '            "linkedin_partner_approved": False,',
)

# ── FIX 3 · /api/narrative/acquisition ─────────────────────────
edit(
    "acquisition prompt: latency line",
    "- Latency: sub-100ms candidate scoring",
    "- Latency: ~35ms median app-layer response (Azure metrics); AI scoring is model-bound at 1-4s, standard for GPT-4o",
)

edit(
    "acquisition fallback narrative",
    "The platform delivers sub-100ms candidate scoring via Azure OpenAI GPT-4o — a technical benchmark no competitor has matched at scale. With 40 production phases spanning AI scorecards, real-time candidate signals, recruiter coaching, predictive hiring funnels, and scenario simulation, AITMP is not a prototype — it is a fully-deployed enterprise platform.\n\nThe competitive moat is threefold: latency (sub-100ms is table stakes for LinkedIn's real-time feed integration), intelligence depth (coaching + signals + narrative in one unified API), and enterprise readiness (Stripe billing, webhook infrastructure, API key management, SSO).",
    "The platform delivers multi-dimensional candidate scoring via Azure OpenAI GPT-4o, backed by a fast API layer (~35ms median app response). With production phases spanning AI scorecards, real-time candidate signals, recruiter coaching, predictive hiring funnels, and scenario simulation, AITMP is not a prototype — it is a fully-deployed enterprise platform.\n\nThe competitive moat is twofold: intelligence depth (scoring + coaching + signals + narrative in one unified API), and enterprise readiness (Stripe billing, webhook infrastructure, API key management, SSO).",
)

edit(
    "acquisition fallback closing line",
    "AITMP's 40-phase architecture, sub-100ms proof, and production-grade codebase make this the highest-leverage acqui-hire in the talent tech space in 2026.",
    "AITMP's deep architecture and production-grade codebase make this a high-leverage acquisition in the talent tech space in 2026.",
)

# ── BONUS · real bug: wrong password field in mobile auth ──────
edit(
    "bugfix: mobile auth password field",
    "    import bcrypt\n    if not bcrypt.checkpw(password.encode(), user.hashed_password.encode()):",
    "    if not verify_password(password, user.password):",
)


# ── VERIFY ─────────────────────────────────────────────────────
print("\n" + "=" * 60)

if errors:
    print("❌ ABORTED — nothing was changed.\n")
    print("These edits didn't match your file exactly:")
    for e in errors:
        print("   •", e)
    print("\nYour main.py may differ slightly from what was reviewed.")
    print("Nothing was written. Your file is untouched.")
    sys.exit(1)

# Does the result still parse as valid Python?
try:
    ast.parse(src)
except SyntaxError as e:
    print("❌ ABORTED — result would be invalid Python:")
    print("   ", e)
    print("Nothing was written. Your file is untouched.")
    sys.exit(1)

# Confirm the bad claims are actually gone
leftovers = []
for bad in ["sub-100ms", "Sub-100ms", "linkedin_ready"]:
    if bad in src:
        leftovers.append(bad)

# Back up, then write
shutil.copy(PATH, PATH + ".backup")
open(PATH, "w", encoding="utf-8").write(src)

print("✅ SUCCESS — main.py patched.\n")
print(f"Backup saved to: {PATH}.backup")
print(f"Edits applied: {len(applied)}")
for a in applied:
    print("   ✓", a)

if leftovers:
    print("\n⚠️  Note: these strings still appear somewhere in the file:")
    for l in leftovers:
        print("   •", l)
    print("   (Probably in a comment or a spot not reviewed — worth a look.)")
else:
    print("\n✓ No 'sub-100ms' or 'linkedin_ready' claims remain.")

print("\nNext: deploy the same way you deployed the landing page.")
print("=" * 60)