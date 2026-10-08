"""
Anonymized description of a job for the public ApplyPilot log.

The real title often identifies the employer ("Backend Engineer, AI Engineering:
Duo Chat" is obviously GitLab), so Claude generalizes it. The company name is
only ever published when the job's `show_public` flag is set in the dashboard.
"""
import json
import sqlite3

from config import DB_PATH
from llm import structured, obj, STR

SCHEMA = obj({
    "role": STR,
    "industry": STR,
    "seniority": {"type": "string", "enum": ["Entry", "Mid", "Senior", "Staff+", "Manager", "Unknown"]},
})

PROMPT = """Describe this job for a public, anonymized activity log.

- role: a generic 2-5 word role name with NO product, team or company names
  (e.g. "Backend Engineer (AI)", "IT Systems Administrator", "Frontend Engineer").
- industry: a 1-3 word industry (e.g. "Fintech", "Developer tools", "Healthcare IT").
- seniority: best guess from the title/description.
Never include anything that would identify the employer.

Title: {title}
Company (for context only, do not output): {company}
Description: {description}"""


def describe(title: str, company: str, description: str) -> dict:
    return structured(PROMPT.format(title=title, company=company,
                                    description=(description or "")[:2500]),
                      SCHEMA, effort="low", max_tokens=2000)


def ensure_meta(job_id: str, conn=None) -> None:
    own = conn is None
    conn = conn or sqlite3.connect(str(DB_PATH))
    r = conn.execute("SELECT title, company, description, public_meta FROM jobs WHERE id=?",
                     (job_id,)).fetchone()
    if r and not r[3]:
        meta = describe(r[0] or "", r[1] or "", r[2] or "")
        conn.execute("UPDATE jobs SET public_meta=? WHERE id=?", (json.dumps(meta), job_id))
        conn.commit()
    if own:
        conn.close()


if __name__ == "__main__":
    # Backfill: every job that got tailored documents.
    from db import ensure_columns
    ensure_columns()
    c = sqlite3.connect(str(DB_PATH))
    ids = [r[0] for r in c.execute(
        "SELECT id FROM jobs WHERE status='ready' AND public_meta IS NULL")]
    for jid in ids:
        try:
            ensure_meta(jid, c)
            print("ok", jid)
        except Exception as e:
            print("fail", jid, e)
    c.close()
