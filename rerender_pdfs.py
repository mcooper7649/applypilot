#!/usr/bin/env python3
"""
Re-render every stored resume/cover-letter PDF from the content saved in the DB
(resume_json / score_json) using the CURRENT templates in documents/pdf_builder.py.

Use this after a layout/template change to refresh existing PDFs in place — no
API calls, no re-fetching postings. Jobs generated before persistence was added
(no resume_json) are skipped and reported.

Run inside the job-bot image:
  docker run --rm -v ~/job-bot:/app -v ~/job-bot/output:/app/output job-bot \
    python3 rerender_pdfs.py
"""
import json
import sqlite3

from config import DB_PATH
from documents.pdf_builder import build_resume_pdf, build_cover_letter_pdf

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT * FROM jobs WHERE status = 'ready' ORDER BY created_at DESC"
).fetchall()
conn.close()

rebuilt, skipped = 0, 0
for r in rows:
    if not r["resume_json"]:
        print(f"  skip (no saved content): {r['company']} — {r['title']}")
        skipped += 1
        continue

    resume_data = json.loads(r["resume_json"])
    score_data = json.loads(r["score_json"]) if r["score_json"] else {}
    job = {
        "company": r["company"],
        "title": r["title"],
        "role_type": score_data.get("role_type", "fullstack"),
    }

    if r["resume_path"]:
        build_resume_pdf(resume_data, r["resume_path"], job)
    # Cover letter text isn't separately stored; only re-render if we kept it.
    cover_text = resume_data.get("_cover_letter")
    if cover_text and r["cover_letter_path"]:
        build_cover_letter_pdf(cover_text, r["cover_letter_path"], job)

    print(f"  rebuilt: {r['company']} — {r['title']}")
    rebuilt += 1

print(f"\nDone. Rebuilt {rebuilt} resume PDF(s); skipped {skipped} (pre-persistence).")
