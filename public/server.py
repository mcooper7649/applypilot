#!/usr/bin/env python3
"""
ApplyPilot public API — read-only, anonymized view of the job-bot database for
applypilot.mycodedojo.com.

Runs in its own container with only this directory and data/ (read-only)
mounted: it can't reach the dashboard, the worker, the profile editor or the
tailored documents. Company names are published only for jobs you opted in
(show_public=1); everything else is the anonymized role/industry from
public_meta.py.
"""
import json
import os
import sqlite3
import time
from collections import Counter

from flask import Flask, jsonify

DB = os.getenv("JOBS_DB", "/data/jobs.db")
CACHE_SECONDS = 60
# Rough, deliberately conservative manual-effort estimates used for "time saved".
MIN_PER_TAILORED = 25   # reading the posting + rewriting resume + cover letter
MIN_PER_FIELD = 0.5     # typing / choosing one form answer

app = Flask(__name__)
_cache: dict = {}


def rows():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    out = conn.execute("SELECT * FROM jobs").fetchall()
    conn.close()
    return out


def stage(r) -> str:
    if r["app_status"] in ("interview", "offer", "rejected"):
        return r["app_status"]
    if r["apply_status"] == "submitted" or r["app_status"] == "applied":
        return "submitted"
    if r["apply_fields"]:
        return "auto-filled"
    return "tailored"


def fill_counts(r):
    if not r["apply_fields"]:
        return None
    fields = json.loads(r["apply_fields"]).get("fields", [])
    auto = sum(1 for f in fields if f.get("source") in ("profile", "standing_answers", "qa_bank"))
    reviewed = sum(1 for f in fields if f.get("source") in ("user", "approved", "drafted", "unknown"))
    return {"total": len(fields), "auto": auto, "reviewed": reviewed}


def build():
    all_rows = rows()
    ready = [r for r in all_rows if r["status"] == "ready"]
    fills = [c for c in (fill_counts(r) for r in ready) if c]
    fields_total = sum(c["total"] for c in fills)
    fields_auto = sum(c["auto"] for c in fills)
    stages = Counter(stage(r) for r in ready)
    scored = [r["fit_score"] for r in all_rows if r["fit_score"]]

    log = []
    for r in sorted(ready, key=lambda r: r["created_at"] or "", reverse=True)[:60]:
        meta = json.loads(r["public_meta"]) if r["public_meta"] else {}
        log.append({
            "date": (r["created_at"] or "")[:10],
            "role": meta.get("role") or "Software role",
            "industry": meta.get("industry") or "",
            "seniority": meta.get("seniority") or "",
            "company": r["company"] if r["show_public"] else None,
            "ats": (r["ats"] or ("adzuna" if r["source"] != "manual" else "other")).title(),
            "source": "Pasted link" if r["source"] == "manual" else "Daily scan",
            "fit": r["fit_score"],
            "fields": fill_counts(r),
            "stage": stage(r),
        })

    minutes = len(ready) * MIN_PER_TAILORED + fields_auto * MIN_PER_FIELD
    stats = {
        "postings_scanned": len(all_rows),
        "tailored": len(ready),
        "auto_filled": len(fills),
        "submitted": stages["submitted"] + stages["interview"] + stages["offer"] + stages["rejected"],
        "interviews": stages["interview"] + stages["offer"],
        "avg_fit": round(sum(scored) / len(scored)) if scored else None,
        "fields_total": fields_total,
        "fields_auto": fields_auto,
        "auto_rate": round(100 * fields_auto / fields_total) if fields_total else None,
        "hours_saved": round(minutes / 60, 1),
        "ats": dict(Counter((r["ats"] or "adzuna").title() for r in ready)),
        "funnel": [
            {"label": "Postings scanned", "n": len(all_rows)},
            {"label": "Tailored resume + cover letter", "n": len(ready)},
            {"label": "Form auto-filled", "n": len(fills)},
            {"label": "Submitted", "n": stages["submitted"] + stages["interview"]
                                         + stages["offer"] + stages["rejected"]},
            {"label": "Interview", "n": stages["interview"] + stages["offer"]},
        ],
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return {"stats": stats, "log": log}


def cached():
    if not _cache or time.time() - _cache["at"] > CACHE_SECONDS:
        _cache.update(at=time.time(), data=build())
    return _cache["data"]


@app.after_request
def headers(resp):
    resp.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/stats")
def stats():
    return jsonify(cached()["stats"])


@app.route("/log")
def log():
    return jsonify(cached()["log"])


@app.route("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8041)
