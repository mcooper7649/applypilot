#!/usr/bin/env python3
"""
job-bot — daily automated job discovery, scoring, and document generation.
Runs once per day via cron (daily.sh); writes data/latest_results.json.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

from config import MIN_FIT_SCORE, OUTPUT_DIR
from db import init_db, seen_job, save_job
from sources.adzuna import fetch_jobs
from scoring.scorer import score_job
from documents.generator import generate_documents
from documents.pdf_builder import build_resume_pdf, build_cover_letter_pdf
from notifications.telegram_notify import write_results

def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Job Bot starting...")

    # 1. Fetch jobs from all sources
    jobs = fetch_jobs()
    print(f"  Total jobs fetched: {len(jobs)}")

    # 2. Filter already-seen jobs
    new_jobs = [j for j in jobs if not seen_job(j["id"])]
    print(f"  New (unseen) jobs: {len(new_jobs)}")

    qualified = []

    for job in new_jobs:
        print(f"  Scoring: {job['title']} @ {job['company']} ...", end=" ")
        sys.stdout.flush()

        # 3. Score job with Claude
        score_data = score_job(job)
        fit_score = score_data.get("fit_score", 0)
        print(f"score={fit_score}")

        if fit_score < MIN_FIT_SCORE:
            save_job({**job, "fit_score": fit_score, "status": "low_score"})
            continue

        # 4. Generate tailored documents
        print(f"    Generating documents for {job['title']}...")
        docs = generate_documents(job, score_data)

        resume_data = docs.get("resume", {})
        cover_text  = docs.get("cover_letter", "")
        # Keep the cover-letter text alongside the resume content so both PDFs
        # can be re-rendered/edited later from the DB without any API call.
        resume_data["_cover_letter"] = cover_text

        job["role_type"] = score_data.get("role_type", "fullstack")

        # 5. Export PDFs
        slug = f"{job['id']}_{job['company'].replace(' ', '_')[:18]}"
        resume_path = str(OUTPUT_DIR / f"{slug}_resume.pdf")
        cl_path     = str(OUTPUT_DIR / f"{slug}_cover_letter.pdf")

        try:
            build_resume_pdf(resume_data, resume_path, job)
            build_cover_letter_pdf(cover_text, cl_path, job)
        except Exception as e:
            print(f"    PDF error: {e}")
            resume_path = None
            cl_path = None

        job.update({
            "fit_score":          fit_score,
            "score_data":         score_data,
            "resume_path":        resume_path,
            "cover_letter_path":  cl_path,
            "status":             "ready",
            # Persist the generated content so a future template/layout fix can
            # re-render the PDFs without re-calling the API (see rerender_pdfs.py).
            "resume_json":        json.dumps(resume_data),
            "score_json":         json.dumps(score_data),
        })

        save_job(job)
        qualified.append(job)
        print(f"    Saved — score {fit_score}/100")

    print(f"\n  Qualified jobs: {len(qualified)}")

    # 6. Write results JSON for a notifier to pick up
    write_results(qualified, len(new_jobs))

    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Done.")

if __name__ == "__main__":
    run()
