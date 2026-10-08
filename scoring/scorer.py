import json
import re
import anthropic
from config import ANTHROPIC_API_KEY
from profile import load_profile, profile_prompt

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _parse_json(text: str) -> dict:
    text = text.strip()
    # Strip markdown fences
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()
    # Find first { ... } block if extra text exists
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


def score_job(job: dict) -> dict:
    salary_text = (
        f"${job['salary_min']:,.0f} – ${job['salary_max']:,.0f}"
        if job.get("salary_min") and job.get("salary_max")
        else "not specified"
    )

    candidate = profile_prompt(load_profile())

    prompt = f"""Score this job posting for the candidate. Return ONLY a JSON object, no markdown.

CANDIDATE:
{candidate}

JOB:
Title: {job['title']}
Company: {job['company']}
Salary: {salary_text}
Description: {job['description'][:2500]}

Return exactly this JSON (integers/strings only, no comments):
{{"fit_score": 0-100, "match_reason": "2 sentences", "matched_skills": ["skill1","skill2"], "missing_skills": ["skill1"], "role_type": "fullstack|frontend|sysadmin|it_manager|other"}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        return _parse_json(raw)
    except Exception as e:
        print(f"[scorer] error for '{job['title']}': {e}")
        return {"fit_score": 0, "match_reason": "Scoring error", "matched_skills": [], "missing_skills": [], "role_type": "other"}
