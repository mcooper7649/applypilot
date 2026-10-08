#!/usr/bin/env python3
"""
Generate the ApplyPilot walkthrough from a REAL pipeline run on fictional data
(Alex Rivera applying to Northwind Labs), so every number and screenshot on the
public site is genuine output — none of it touches the real profile or jobs.db.

  docs  (job-bot image):       extract posting → score → tailor → render PDFs
  fill  (job-bot-apply image): fill the demo form with the same planner the
                               worker uses, then screenshot it

Run with JOBBOT_PROFILE=/app/public/demo/profile.json (see public/build_demo.sh).
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HERE = Path(__file__).resolve().parent
OUT = HERE / "site" / "demo"
RUN = OUT / "run.json"
JOB_URL = "https://careers.northwind-labs.example/jobs/senior-full-stack-engineer"


def docs():
    from intake.job_fetch import fetch_job
    from scoring.scorer import score_job
    from documents.generator import generate_documents
    from documents.pdf_builder import build_resume_pdf, build_cover_letter_pdf

    job = fetch_job(JOB_URL, (HERE / "demo" / "job.txt").read_text())
    score = score_job(job)
    job["role_type"] = score.get("role_type", "fullstack")
    tailored = generate_documents(job, score)
    resume, cover = tailored["resume"], tailored["cover_letter"]
    build_resume_pdf(resume, str(OUT / "Alex_Rivera_Resume.pdf"), job)
    build_cover_letter_pdf(cover, str(OUT / "Alex_Rivera_Cover_Letter.pdf"), job)

    import fitz  # pymupdf, installed by build_demo.sh for this run only
    for name in ("Alex_Rivera_Resume", "Alex_Rivera_Cover_Letter"):
        page = fitz.open(OUT / f"{name}.pdf")[0]
        page.get_pixmap(dpi=110).save(OUT / f"{name}.png")

    RUN.write_text(json.dumps({
        "job": {k: job[k] for k in ("title", "company", "location", "salary_min",
                                    "salary_max", "ats", "url")}
               | {"description_chars": len(job["description"])},
        "score": score,
        "resume": resume,
        "cover_letter": cover,
    }, indent=2))
    print("docs ok", score.get("fit_score"))


def fill():
    from playwright.sync_api import sync_playwright
    from profile import load_profile
    from apply import form, answers

    run = json.loads(RUN.read_text())
    files = {"resume": str(OUT / "Alex_Rivera_Resume.pdf"),
             "cover_letter": str(OUT / "Alex_Rivera_Cover_Letter.pdf")}
    job = {**run["job"], "description": (HERE / "demo" / "job.txt").read_text()}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        page.goto((OUT / "apply.html").as_uri())
        fields = form.extract_fields(page)
        fields = answers.plan(fields, job, load_profile(), run["cover_letter"])
        for f in fields:
            f["fill_error"] = form.fill_field(page, f, f.get("value"), files)
            if f["fill_error"]:
                f["needs_review"] = True
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "fill.png"), full_page=True)
        browser.close()
    run["fields"] = [{k: f.get(k) for k in ("label", "kind", "required", "value",
                                            "source", "needs_review", "note", "fill_error")}
                     for f in fields]
    RUN.write_text(json.dumps(run, indent=2))
    print("fill ok", len(fields), "fields,", sum(f["needs_review"] for f in fields), "flagged")


if __name__ == "__main__":
    {"docs": docs, "fill": fill}[sys.argv[1]]()
