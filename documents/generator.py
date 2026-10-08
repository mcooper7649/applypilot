import json
import anthropic
from config import ANTHROPIC_API_KEY
from profile import load_profile, profile_prompt

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def generate_documents(job: dict, score_data: dict) -> dict:
    salary_text = (
        f"${job['salary_min']:,.0f} – ${job['salary_max']:,.0f}"
        if job.get("salary_min") and job.get("salary_max")
        else "not listed"
    )

    profile = load_profile()
    candidate = profile_prompt(profile)

    prompt = f"""You are tailoring application documents for the candidate below.

CANDIDATE (these are the ONLY true facts — do not invent or alter any of them):
{candidate}

TARGET JOB:
Title: {job['title']}
Company: {job['company']}
Salary: {salary_text}
Matched skills: {', '.join(score_data.get('matched_skills', []))}
Role type: {score_data.get('role_type')}
Description:
{job['description'][:3500]}

STRICT RULES:
- Use ONLY the candidate's real employers, job titles, dates, skills, and projects above.
- Do NOT invent new jobs, accomplishments, metrics, schools, degrees, or certifications.
- Tailor by REORDERING and REPHRASING the candidate's real experience bullets to lead
  with what is most relevant to this job. You may tighten wording but not fabricate.
- Education and certifications are handled separately — do NOT output them.

Generate two documents:

1. TAILORED RESUME — JSON with exactly these keys:
   - summary: 2-3 sentence profile paragraph tailored to this specific role (factual)
   - experience: array of {{title, company, dates, bullets:[str]}} — same real jobs,
     bullets reordered/rephrased for relevance; keep every job factual
   - skills: object of category -> [skill] — emphasize matched skills first, real skills only;
     at most 5 categories with ~6 skills each (the sidebar is space-limited)
   - projects: array of {{name, description, tech}} — pick the 2-3 most relevant real projects

2. COVER LETTER — plain text, 3 paragraphs (opening naming the company/role, 2-3 concrete
   real examples addressing the requirements, confident closing with a call to action).

Return ONLY valid JSON (no markdown fences, no extra keys):
{{
  "resume": {{
    "summary": "...",
    "experience": [{{"title": "...", "company": "...", "dates": "...", "bullets": ["..."]}}],
    "skills": {{"Category": ["..."]}},
    "projects": [{{"name": "...", "description": "...", "tech": "..."}}]
  }},
  "cover_letter": "..."
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        docs = json.loads(raw)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[generator] parse error: {e}")
        return {
            "resume": {"summary": "See attached profile.", "experience": [], "skills": {}, "projects": []},
            "cover_letter": raw,
        }

    # Belt-and-suspenders: even if the model emits credentials, never trust them —
    # they are rendered from the profile. Strip them from the tailored payload.
    resume = docs.get("resume", {})
    resume.pop("education", None)
    resume.pop("certifications", None)
    docs["resume"] = resume
    return docs
