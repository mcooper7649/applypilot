"""
Single source of truth for the candidate's real, factual profile.

Lives at data/profile.json (on the shared data mount) so the dashboard can edit
it and the bot reads it. Credentials (education, certifications, contact) are
rendered straight from here and are NEVER produced by the LLM, so the bot can't
invent degrees or certs. The LLM only TAILORS summary/experience/skills/projects.
"""
import json
import os
from pathlib import Path

# JOBBOT_PROFILE lets the public demo run the real pipeline with a fictional candidate.
PROFILE_PATH = Path(os.getenv("JOBBOT_PROFILE") or Path(__file__).parent / "data" / "profile.json")


def load_profile() -> dict:
    with open(PROFILE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_profile(profile: dict) -> None:
    # Atomic write within the data dir so a reader never sees a half-written file.
    tmp = PROFILE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    tmp.replace(PROFILE_PATH)


def profile_prompt(profile: dict) -> str:
    """Render the profile as the factual context block fed to the LLM prompts."""
    lines = [
        f"Name: {profile.get('name', '')}",
        f"Title: {profile.get('title', '')}",
        f"Location: {profile.get('location', '')}",
        "",
        "WORK EXPERIENCE:",
    ]
    for i, ex in enumerate(profile.get("experience", []), 1):
        lines.append(f"{i}. {ex.get('title','')} — {ex.get('company','')} ({ex.get('dates','')})")
        for b in ex.get("bullets", []):
            lines.append(f"   - {b}")

    edu = profile.get("education", [])
    if edu:
        lines += ["", "EDUCATION:"]
        for e in edu:
            yr = f" ({e['year']})" if e.get("year") else ""
            lines.append(f"   - {e.get('degree','')} — {e.get('school','')}{yr}")

    certs = profile.get("certifications", [])
    if certs:
        lines += ["", "CERTIFICATIONS:"]
        lines += [f"   - {c}" for c in certs]

    skills = profile.get("skills", {})
    if skills:
        flat = [s for items in skills.values() for s in items]
        lines += ["", "SKILLS: " + ", ".join(flat)]

    projects = profile.get("projects", [])
    if projects:
        lines += ["", "PROJECTS:"]
        for p in projects:
            lines.append(f"   - {p.get('name','')} ({p.get('tech','')}): {p.get('description','')}")

    lines += ["", f"TARGET: {profile.get('target', 'Remote only, $80K+/year')}"]
    return "\n".join(lines)
