"""
Manual intake: a job link pasted into the dashboard → fetched, scored, tailored
resume + cover letter rendered. Same document pipeline as the daily Adzuna run
(main.py); unlike that run, a low score never skips generation because you
picked this job yourself.
"""
import json
import sqlite3
import threading
import traceback
from urllib.parse import urlparse

from config import DB_PATH, OUTPUT_DIR
from db import ensure_columns
from intake.job_fetch import fetch_job, job_id_for, FetchError
from scoring.scorer import score_job
from documents.generator import generate_documents
from documents.pdf_builder import build_resume_pdf, build_cover_letter_pdf
from public_meta import ensure_meta


def _conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _update(job_id: str, **fields):
    conn = _conn()
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), job_id))
    conn.commit()
    conn.close()


def start(url: str, pasted_description: str = "") -> str:
    """Create/reset the job row and process it in a background thread."""
    ensure_columns()
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    job_id = job_id_for(url)
    conn = _conn()
    exists = conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if exists:
        conn.execute("UPDATE jobs SET status='processing', error=NULL WHERE id=?", (job_id,))
    else:
        conn.execute(
            "INSERT INTO jobs (id, title, company, url, status, source) "
            "VALUES (?, ?, ?, ?, 'processing', 'manual')",
            (job_id, "Reading posting…", urlparse(url).netloc, url))
    conn.commit()
    conn.close()
    threading.Thread(target=_process, args=(job_id, url, pasted_description),
                     daemon=True).start()
    return job_id


def _process(job_id: str, url: str, pasted: str):
    try:
        job = fetch_job(url, pasted)
        _update(job_id, title=job["title"], company=job["company"],
                location=job.get("location", ""), description=job["description"],
                salary_min=job.get("salary_min"), salary_max=job.get("salary_max"),
                ats=job["ats"], ats_meta=json.dumps(job.get("ats_meta", {})),
                apply_url=job["apply_url"])

        score = score_job(job)
        job["role_type"] = score.get("role_type", "fullstack")
        docs = generate_documents(job, score)
        resume_data = docs.get("resume", {})
        cover = docs.get("cover_letter", "")
        resume_data["_cover_letter"] = cover

        slug = f"{job_id}_{job['company'].replace(' ', '_')[:18]}"
        resume_path = str(OUTPUT_DIR / f"{slug}_resume.pdf")
        cover_path = str(OUTPUT_DIR / f"{slug}_cover_letter.pdf")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        build_resume_pdf(resume_data, resume_path, job)
        build_cover_letter_pdf(cover, cover_path, job)

        _update(job_id, fit_score=score.get("fit_score", 0), status="ready",
                resume_path=resume_path, cover_letter_path=cover_path,
                resume_json=json.dumps(resume_data), score_json=json.dumps(score),
                error=None)
        try:
            ensure_meta(job_id)
        except Exception:
            traceback.print_exc()   # showcase metadata is best-effort
    except FetchError as e:
        _update(job_id, status="error", error=str(e))
    except Exception as e:
        traceback.print_exc()
        _update(job_id, status="error", error=f"{type(e).__name__}: {e}")
