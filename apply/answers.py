"""
Decide what goes in each application field.

Order of precedence for a field's value:
  1. what you typed/approved in the dashboard review for this job (source=user)
  2. deterministic profile mapping (name, email, phone, links, resume/cover files)
  3. Claude, given your profile, standing answers and saved Q&A bank — it must
     say where each answer came from and flag anything it couldn't ground in
     real facts (needs_review), and it leaves unknowns blank rather than guess.
"""
import json
import re

from llm import structured, obj, STR
from profile import profile_prompt

DEFAULT_APP_ANSWERS = {
    "address_street": "",          # used only when a form asks for a mailing address
    "address_city": "",
    "address_state": "",
    "address_zip": "",
    "address_county": "",
    "work_authorization": "",      # e.g. "Yes — US citizen, authorized to work in the US"
    "requires_sponsorship": "",    # e.g. "No"
    "salary_expectation": "",      # e.g. "$120,000"
    "earliest_start": "",          # e.g. "Two weeks after offer"
    "willing_to_relocate": "",     # e.g. "No — remote only"
    "how_did_you_hear": "",        # e.g. "Company careers page"
    "gender": "Decline to self-identify",
    "race_ethnicity": "Decline to self-identify",
    "hispanic_latino": "Decline to self-identify",
    "veteran_status": "I don't wish to answer",
    "disability_status": "I don't want to answer",
}

_RULES = [  # (label regex, value getter, kinds it applies to)
    (r"^(legal )?first name|given name", lambda p: p["name"].split()[0], ("text",)),
    (r"^(legal )?last name|family name|surname", lambda p: p["name"].split()[-1], ("text",)),
    (r"^(full |legal |your )?name$", lambda p: p["name"], ("text",)),
    (r"e ?mail", lambda p: p["contact"]["email"], ("text",)),
    (r"phone|mobile", lambda p: p["contact"]["phone"], ("text",)),
    (r"linkedin", lambda p: _url(p["contact"].get("linkedin")), ("text",)),
    (r"github", lambda p: _url(p["contact"].get("github")), ("text",)),
    (r"website|portfolio|personal (site|url)", lambda p: _url(p["contact"].get("website")), ("text",)),
    (r"address line 1|street address|^address$|^street", lambda p: _addr(p, "street"), ("text", "combobox")),
    (r"address line 2|\bapt\b|\bsuite\b", lambda p: "", ("text",)),
    (r"^(city|town)\b", lambda p: _addr(p, "city"), ("text", "combobox")),
    (r"^county\b", lambda p: _addr(p, "county"), ("text",)),
    (r"^(state|province)\b", lambda p: _addr(p, "state"), ("text", "combobox", "select")),
    (r"zip|postal", lambda p: _addr(p, "zip"), ("text",)),
    (r"resume|\bcv\b", lambda p: "resume", ("file",)),
    (r"cover letter", lambda p: "cover_letter", ("file",)),
]


def _addr(p, part):
    return (p.get("application_answers") or {}).get(f"address_{part}", "")


def _url(v):
    if not v:
        return ""
    return v if v.startswith("http") else "https://" + v


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _deterministic(f, profile, cover_text):
    label = _norm(f["label"]) or _norm(f["name"])
    if f["kind"] == "file":   # upload buttons are often just labelled "Attach"
        label = f"{label} {_norm(f['name'])}"
    if f["kind"] == "textarea" and re.search(r"cover letter", label):
        return cover_text
    for rx, get, kinds in _RULES:
        if f["kind"] in kinds and re.search(rx, label):
            try:
                return get(profile)
            except (KeyError, IndexError):
                return None
    return None


ANSWER_SCHEMA = obj({"answers": {"type": "array", "items": obj({
    "key": STR,
    "value": STR,
    "source": {"type": "string", "enum": ["profile", "standing_answers", "qa_bank",
                                          "drafted", "unknown"]},
    "needs_review": {"type": "boolean"},
    "note": STR,
})}})


def _llm_answers(fields, job, profile, cover_text):
    app = {**DEFAULT_APP_ANSWERS, **profile.get("application_answers", {})}
    bank = profile.get("qa_bank", [])
    questions = [{"key": f["key"], "question": f["label"], "type": f["kind"],
                  "required": f["required"], "options": f["options"]} for f in fields]
    prompt = f"""You are filling out a job application on behalf of the candidate.

CANDIDATE PROFILE (true facts):
{profile_prompt(profile)}

STANDING ANSWERS the candidate set for common application questions ("" = not set):
{json.dumps(app, indent=1)}

PREVIOUSLY APPROVED ANSWERS (Q&A bank):
{json.dumps(bank, indent=1)}

JOB: {job['title']} at {job['company']}
{(job.get('description') or '')[:5000]}

COVER LETTER already written for this job (reuse its substance for "why us" questions):
{cover_text[:2500]}

FORM QUESTIONS:
{json.dumps(questions, indent=1)}

Answer every question. Rules:
- For select/radio/combobox questions with options, `value` must be copied EXACTLY
  from the options list. For multi-select checkboxes join choices with " | ".
- For a single checkbox (e.g. consent/acknowledgement), answer "yes" or "no".
- Never state anything the profile, standing answers or Q&A bank don't support.
  Legal/eligibility answers (work authorization, sponsorship, background checks,
  salary) come ONLY from standing answers — if that answer is "", set value "",
  source "unknown", needs_review true.
- EEO/demographic questions: use the standing answer, mapped to the closest option.
- Short factual questions (years of experience with X, current title, etc.):
  derive from the profile; source "profile". If it's a judgement call, needs_review true.
- Open-ended/essay questions: write a concise, specific answer from real profile
  facts (source "drafted", needs_review true).
- If you can't answer truthfully, leave value "" with source "unknown",
  needs_review true, and a short `note` saying what's missing.
- `note`: one short line on where the answer came from or why it needs review."""
    out = structured(prompt, ANSWER_SCHEMA, effort="medium")
    return {a["key"]: a for a in out["answers"]}


def plan(fields, job, profile, cover_text, prior=None):
    """Annotate each field with value/source/needs_review/note. `prior` maps key → field
    dict from an earlier fill (carrying the user's reviewed values)."""
    prior = prior or {}
    pending = []
    for f in fields:
        p = prior.get(f["key"])
        if p and p.get("source") in ("user", "approved"):
            f.update(value=p["value"], source=p["source"], needs_review=False, note=p.get("note", ""))
            continue
        v = _deterministic(f, profile, cover_text)
        if v:
            f.update(value=v, source="profile", needs_review=False, note="")
        elif f["kind"] == "file":
            f.update(value="", source="unknown", needs_review=f["required"],
                     note="unrecognized upload field")
        else:
            pending.append(f)

    if pending:
        answers = _llm_answers(pending, job, profile, cover_text)
        for f in pending:
            a = answers.get(f["key"], {"value": "", "source": "unknown",
                                       "needs_review": True, "note": "no answer returned"})
            if f["required"]:
                needs = a["needs_review"] or not a["value"]
            else:   # optional + blank is fine; optional + drafted text still gets a look
                needs = a["needs_review"] and bool(a["value"])
            f.update(value=a["value"], source=a["source"], needs_review=needs, note=a["note"])
    for f in fields:
        if f["kind"] == "checkbox" and isinstance(f.get("value"), str) and " | " in f["value"]:
            f["value"] = [v.strip() for v in f["value"].split(" | ")]
    return fields
