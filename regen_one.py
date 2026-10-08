#!/usr/bin/env python3
"""Regenerate documents for a single job id (re-fetches the posting for context).
Usage: python3 regen_one.py <job_id>"""
import sys, re, json, sqlite3
import requests
from config import DB_PATH
from scoring.scorer import score_job
from documents.generator import generate_documents
from documents.pdf_builder import build_resume_pdf, build_cover_letter_pdf

job_id = sys.argv[1]
conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row
r = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
if not r:
    print("no such job"); sys.exit(1)

desc = ""
try:
    html = requests.get(r["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    desc = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", html)).strip()[:3500]
except Exception as e:
    print("desc fetch failed (continuing generic):", e)

job = {"id": r["id"], "title": r["title"], "company": r["company"], "url": r["url"],
       "salary_min": r["salary_min"], "salary_max": r["salary_max"], "description": desc}

score = score_job(job)
job["role_type"] = score.get("role_type", "fullstack")
docs = generate_documents(job, score)
resume_data = docs.get("resume", {})
resume_data["_cover_letter"] = docs.get("cover_letter", "")

build_resume_pdf(resume_data, r["resume_path"], job)
if r["cover_letter_path"]:
    build_cover_letter_pdf(docs.get("cover_letter", ""), r["cover_letter_path"], job)

conn.execute("UPDATE jobs SET resume_json=?, score_json=?, fit_score=?, status='ready' WHERE id=?",
             (json.dumps(resume_data), json.dumps(score), score.get("fit_score", r["fit_score"]), job_id))
conn.commit(); conn.close()
print(f"regenerated {r['company']} — {r['title']} (fit {score.get('fit_score')}, desc {len(desc)} chars)")
