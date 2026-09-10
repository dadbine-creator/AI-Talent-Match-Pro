from app.ai_engine import run_full_talent_match

results = run_full_talent_match(
    "Head of Product",
    "We are a founder-led SaaS startup scaling from Series A to B. 
     We need someone who brings clarity and calm to chaos."
)

print(results)
