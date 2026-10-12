import sqlite3
from config import DB_PATH

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id              TEXT PRIMARY KEY,
            title           TEXT,
            company         TEXT,
            url             TEXT,
            salary_min      REAL,
            salary_max      REAL,
            fit_score       INTEGER,
            status          TEXT DEFAULT 'new',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resume_path     TEXT,
            cover_letter_path TEXT,
            resume_json     TEXT,
            score_json      TEXT
        )
    """)
    conn.commit()
    conn.close()
    ensure_columns()


# Columns added after the original schema. Bot owns status/resume_json/score_json;
# the dashboard owns app_status/applied_at/notes; manual intake + the apply worker
# own the rest.
EXTRA_COLUMNS = {
    "app_status": "TEXT", "applied_at": "TEXT", "notes": "TEXT",
    "resume_json": "TEXT", "score_json": "TEXT",
    "source": "TEXT", "location": "TEXT", "description": "TEXT", "error": "TEXT",
    "ats": "TEXT", "ats_meta": "TEXT", "apply_url": "TEXT",
    # apply worker: apply_status ∈ fill_requested → filling → awaiting_review →
    # submit_requested → submitting → submitted | needs_manual | failed
    "apply_status": "TEXT", "apply_fields": "TEXT", "apply_log": "TEXT",
    "apply_updated": "TEXT",
    # public showcase: anonymized role/industry (public_meta.py) + per-job opt-in
    # to show the company name on applypilot.cc
    "public_meta": "TEXT", "show_public": "INTEGER DEFAULT 0",
}


def ensure_columns():
    conn = sqlite3.connect(DB_PATH)
    have = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    for col, typ in EXTRA_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
    conn.commit()
    conn.close()

def seen_job(job_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return row is not None

def save_job(job: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR IGNORE INTO jobs
            (id, title, company, url, salary_min, salary_max, fit_score, status,
             resume_path, cover_letter_path, resume_json, score_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job["id"], job.get("title"), job.get("company"), job.get("url"),
        job.get("salary_min"), job.get("salary_max"),
        job.get("fit_score"), job.get("status", "new"),
        job.get("resume_path"), job.get("cover_letter_path"),
        job.get("resume_json"), job.get("score_json"),
    ))
    conn.commit()
    conn.close()

def get_recent_jobs(limit: int = 50):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows
