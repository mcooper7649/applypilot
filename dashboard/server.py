#!/usr/bin/env python3
"""
job-bot dashboard — runs ON the job-bot Docker image so it shares the bot's code
(WeasyPrint for re-rendering, the Anthropic SDK for crawling). Provides:

  - the application tracker (jobs, pipeline status, notes, PDF links)
  - a Profile editor (single source of truth for the candidate's real facts)
  - per-job resume editing with instant PDF re-render (no API call)
  - "Import from my links" — crawl website/GitHub/LinkedIn and propose profile data
"""
import os
import re
import sys
import json
import sqlite3

# Make the bot's top-level modules importable (config, profile, documents.*).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from flask import Flask, render_template, jsonify, request, send_from_directory, abort

from config import DB_PATH, OUTPUT_DIR, ANTHROPIC_API_KEY
from profile import load_profile, save_profile
from db import ensure_columns
from intake import pipeline as intake
from intake.resume_parse import parse_resume, safe_filename
from documents.pdf_builder import build_resume_pdf, build_cover_letter_pdf

OUTPUT_DIR = str(OUTPUT_DIR)
PIPELINE = ["to_apply", "applied", "interview", "offer", "rejected", "skipped"]

app = Flask(__name__)


# ── DB helpers ───────────────────────────────────────────────────────────────
def connect():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def row_to_job(r):
    d = dict(r)
    d["resume_file"] = os.path.basename(r["resume_path"]) if r["resume_path"] else None
    d["cover_file"] = os.path.basename(r["cover_letter_path"]) if r["cover_letter_path"] else None
    d["has_content"] = bool(r["resume_json"])
    if not d.get("app_status"):
        d["app_status"] = "to_apply" if r["status"] == "ready" else r["status"]
    for k in ("resume_json", "score_json", "description", "ats_meta", "apply_fields", "apply_log"):
        d.pop(k, None)
    return d


# ── Pages & tracker API ──────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/jobs")
def api_jobs():
    conn = connect()
    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    conn.close()
    jobs = [row_to_job(r) for r in rows]
    ready = [j for j in jobs if j["status"] == "ready"]
    summary = {
        "total": len(jobs),
        "ready": len(ready),
        "applied": sum(1 for j in jobs if j["app_status"] == "applied"),
        "interview": sum(1 for j in jobs if j["app_status"] == "interview"),
        "offer": sum(1 for j in jobs if j["app_status"] == "offer"),
        "rejected": sum(1 for j in jobs if j["app_status"] == "rejected"),
        "to_apply": sum(1 for j in ready if j["app_status"] == "to_apply"),
    }
    return jsonify({"jobs": jobs, "summary": summary, "pipeline": PIPELINE})


@app.route("/api/jobs/<job_id>", methods=["POST"])
def api_update(job_id):
    data = request.get_json(force=True) or {}
    fields, values = [], []
    if "app_status" in data:
        if data["app_status"] not in PIPELINE:
            return jsonify({"error": "invalid status"}), 400
        fields.append("app_status = ?")
        values.append(data["app_status"])
        if data["app_status"] == "applied":
            from datetime import datetime, timezone
            fields.append("applied_at = COALESCE(applied_at, ?)")
            values.append(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if "notes" in data:
        fields.append("notes = ?")
        values.append(data["notes"])
    if "show_public" in data:
        fields.append("show_public = ?")
        values.append(1 if data["show_public"] else 0)
    if not fields:
        return jsonify({"error": "nothing to update"}), 400
    values.append(job_id)
    conn = connect()
    cur = conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    changed = cur.rowcount
    conn.close()
    if not changed:
        return jsonify({"error": "job not found"}), 404
    return jsonify({"ok": True})


@app.route("/pdf/<job_id>/<kind>")
def pdf(job_id, kind):
    if kind not in ("resume", "cover"):
        abort(404)
    col = "resume_path" if kind == "resume" else "cover_letter_path"
    conn = connect()
    row = conn.execute(f"SELECT {col} AS p FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not row or not row["p"]:
        abort(404)
    fname = os.path.basename(row["p"])
    if not os.path.exists(os.path.join(OUTPUT_DIR, fname)):
        abort(404)
    return send_from_directory(OUTPUT_DIR, fname, mimetype="application/pdf")


# ── Profile editor ───────────────────────────────────────────────────────────
@app.route("/api/profile", methods=["GET"])
def api_profile_get():
    return jsonify(load_profile())


@app.route("/api/profile", methods=["POST"])
def api_profile_post():
    data = request.get_json(force=True) or {}
    if not isinstance(data, dict) or "name" not in data:
        return jsonify({"error": "invalid profile"}), 400
    # Merge onto the existing profile so partial saves don't drop fields.
    profile = load_profile()
    profile.update(data)
    save_profile(profile)
    return jsonify({"ok": True, "profile": profile})


# ── Per-job resume editing + instant re-render ───────────────────────────────
@app.route("/api/jobs/<job_id>/resume", methods=["GET"])
def api_resume_get(job_id):
    conn = connect()
    r = conn.execute(
        "SELECT resume_json, company, title FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    conn.close()
    if not r:
        return jsonify({"error": "job not found"}), 404
    if not r["resume_json"]:
        return jsonify({"error": "no editable content for this job"}), 404
    data = json.loads(r["resume_json"])
    cover = data.pop("_cover_letter", "")
    return jsonify({
        "resume": {k: data.get(k) for k in ("summary", "experience", "skills", "projects")},
        "cover_letter": cover,
        "company": r["company"],
        "title": r["title"],
    })


@app.route("/api/jobs/<job_id>/resume", methods=["POST"])
def api_resume_post(job_id):
    body = request.get_json(force=True) or {}
    resume = body.get("resume")
    if not isinstance(resume, dict):
        return jsonify({"error": "missing resume"}), 400

    conn = connect()
    r = conn.execute(
        "SELECT resume_path, cover_letter_path, score_json, company, title FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if not r:
        conn.close()
        return jsonify({"error": "job not found"}), 404

    score = json.loads(r["score_json"]) if r["score_json"] else {}
    cover_text = body.get("cover_letter", "")
    resume_data = dict(resume)
    resume_data["_cover_letter"] = cover_text

    conn.execute("UPDATE jobs SET resume_json = ? WHERE id = ?",
                 (json.dumps(resume_data), job_id))
    conn.commit()
    conn.close()

    job = {"company": r["company"], "title": r["title"],
           "role_type": score.get("role_type", "fullstack")}
    try:
        if r["resume_path"]:
            build_resume_pdf(resume_data, r["resume_path"], job)
        if cover_text and r["cover_letter_path"]:
            build_cover_letter_pdf(cover_text, r["cover_letter_path"], job)
    except Exception as e:
        return jsonify({"error": f"render failed: {e}"}), 500
    return jsonify({"ok": True})


# ── Import from links (crawl website / GitHub / LinkedIn) ────────────────────
def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_url(url: str) -> str:
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    headers = {"User-Agent": "Mozilla/5.0 (compatible; job-bot-dashboard/1.0)"}
    r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
    r.raise_for_status()
    return r.text


def _github_summary(handle: str) -> str:
    m = re.search(r"github\.com/([A-Za-z0-9-]+)", handle)
    user = m.group(1) if m else handle.strip().strip("/")
    if not user:
        return ""
    headers = {"User-Agent": "job-bot-dashboard", "Accept": "application/vnd.github+json"}
    out = []
    try:
        u = requests.get(f"https://api.github.com/users/{user}", headers=headers, timeout=20).json()
        out.append(f"GitHub user {user}: name={u.get('name')}, bio={u.get('bio')}, "
                   f"company={u.get('company')}, blog={u.get('blog')}, location={u.get('location')}")
        repos = requests.get(
            f"https://api.github.com/users/{user}/repos?sort=pushed&per_page=30",
            headers=headers, timeout=20,
        ).json()
        if isinstance(repos, list):
            out.append("Repositories:")
            for repo in repos:
                if repo.get("fork"):
                    continue
                out.append(f"- {repo.get('name')} ({repo.get('language')}): "
                           f"{repo.get('description') or ''} "
                           f"[topics: {', '.join(repo.get('topics', []))}]")
    except Exception as e:
        out.append(f"(GitHub fetch error: {e})")
    return "\n".join(out)


IMPORT_SCHEMA_HINT = """{
  "summary": "one-paragraph professional summary if clearly stated, else \\"\\"",
  "education": [{"degree": "...", "school": "...", "year": "..."}],
  "certifications": ["..."],
  "skills": {"Category": ["skill"]},
  "projects": [{"name": "...", "tech": "...", "description": "..."}],
  "experience": [{"title": "...", "company": "...", "dates": "...", "bullets": ["..."]}]
}"""


@app.route("/api/profile/import", methods=["POST"])
def api_profile_import():
    body = request.get_json(force=True) or {}
    sources, status = [], {}

    if body.get("website"):
        try:
            txt = _strip_html(_fetch_url(body["website"]))[:8000]
            sources.append(f"WEBSITE ({body['website']}):\n{txt}")
            status["website"] = "ok" if txt else "empty"
        except Exception as e:
            status["website"] = f"error: {e}"

    if body.get("github"):
        gh = _github_summary(body["github"])
        sources.append(f"GITHUB:\n{gh}")
        status["github"] = "ok" if gh and "error" not in gh else "error"

    if body.get("linkedin"):
        try:
            txt = _strip_html(_fetch_url(body["linkedin"]))[:4000]
            # LinkedIn almost always returns a login wall for anonymous fetches.
            blocked = "sign in" in txt.lower() or "join linkedin" in txt.lower() or len(txt) < 200
            status["linkedin"] = "blocked (login wall)" if blocked else "ok"
            if not blocked:
                sources.append(f"LINKEDIN:\n{txt}")
        except Exception as e:
            status["linkedin"] = f"error: {e}"

    if not sources:
        return jsonify({"suggestions": {}, "sources": status,
                        "note": "No usable content fetched."}), 200

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = (
        "Extract real profile facts from the source text below. Use ONLY information "
        "explicitly present — do NOT invent or guess degrees, employers, dates, or certs. "
        "Omit anything not clearly stated. Return ONLY this JSON shape:\n"
        f"{IMPORT_SCHEMA_HINT}\n\nSOURCE TEXT:\n" + "\n\n".join(sources)[:18000]
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        suggestions = json.loads(m.group(0) if m else raw)
    except Exception as e:
        return jsonify({"error": f"extraction failed: {e}", "sources": status}), 500

    return jsonify({"suggestions": suggestions, "sources": status})


# ── Resume upload → profile suggestions ──────────────────────────────────────
UPLOAD_DIR = os.path.join(os.path.dirname(str(DB_PATH)), "uploads")


@app.route("/api/profile/resume", methods=["POST"])
def api_profile_resume():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file"}), 400
    data = f.read()
    if len(data) > 10 * 1024 * 1024:
        return jsonify({"error": "file over 10 MB"}), 400
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_DIR, safe_filename(f.filename)), "wb") as out:
        out.write(data)
    try:
        suggestions = parse_resume(f.filename, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"extraction failed: {e}"}), 500
    return jsonify({"suggestions": suggestions, "sources": {"resume": f"ok ({f.filename})"}})


# ── Add a job by link ────────────────────────────────────────────────────────
@app.route("/api/jobs/from-url", methods=["POST"])
def api_job_from_url():
    body = request.get_json(force=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url required"}), 400
    job_id = intake.start(url, body.get("description", ""))
    return jsonify({"ok": True, "id": job_id})


@app.route("/api/jobs/<job_id>", methods=["DELETE"])
def api_job_delete(job_id):
    conn = connect()
    cur = conn.execute("DELETE FROM jobs WHERE id = ? AND source = 'manual'", (job_id,))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        return jsonify({"error": "only manually added jobs can be removed"}), 400
    return jsonify({"ok": True})


# ── Apply assistant (worker container does the browser work) ─────────────────
APPLY_DIR = os.path.join(os.path.dirname(str(DB_PATH)), "apply")
STANDARD_FIELDS = {"first name", "last name", "name", "email", "phone", "resume", "cover letter"}


@app.route("/api/jobs/<job_id>/apply", methods=["GET"])
def api_apply_get(job_id):
    conn = connect()
    r = conn.execute("SELECT id, company, title, apply_url, url, ats, apply_status, "
                     "apply_fields, apply_log, apply_updated FROM jobs WHERE id = ?",
                     (job_id,)).fetchone()
    conn.close()
    if not r:
        return jsonify({"error": "job not found"}), 404
    d = dict(r)
    d["apply_fields"] = json.loads(r["apply_fields"]) if r["apply_fields"] else {}
    return jsonify(d)


def _set_apply_status(job_id, status, allowed_from=None):
    conn = connect()
    sql = "UPDATE jobs SET apply_status = ?, apply_updated = datetime('now') WHERE id = ?"
    args = [status, job_id]
    if allowed_from is not None:
        sql += f" AND COALESCE(apply_status,'') IN ({','.join('?' * len(allowed_from))})"
        args += allowed_from
    cur = conn.execute(sql, args)
    conn.commit()
    conn.close()
    return cur.rowcount


@app.route("/api/jobs/<job_id>/apply/fill", methods=["POST"])
def api_apply_fill(job_id):
    conn = connect()
    r = conn.execute("SELECT status, resume_path FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    if not r or r["status"] != "ready" or not r["resume_path"]:
        return jsonify({"error": "job has no tailored documents yet"}), 400
    if not _set_apply_status(job_id, "fill_requested",
                             ["", "awaiting_review", "needs_manual", "failed"]):
        return jsonify({"error": "the worker is already busy with this job"}), 409
    return jsonify({"ok": True})


def _save_answers(job_id, edits):
    """Apply reviewed values (key → value) onto the stored field list."""
    conn = connect()
    r = conn.execute("SELECT apply_fields FROM jobs WHERE id = ?", (job_id,)).fetchone()
    doc = json.loads(r["apply_fields"]) if r and r["apply_fields"] else {}
    for f in doc.get("fields", []):
        if f["key"] in edits:
            new = edits[f["key"]]
            if new != f.get("value"):
                f["value"], f["source"] = new, "user"
            elif f.get("source") != "user":
                f["source"] = "approved"
            f["needs_review"] = False
            f["fill_error"] = None
    conn.execute("UPDATE jobs SET apply_fields = ? WHERE id = ?", (json.dumps(doc), job_id))
    conn.commit()
    conn.close()
    return doc


def _remember_answers(doc):
    """Add reviewed answers to custom questions to the profile's Q&A bank for reuse."""
    profile = load_profile()
    bank = {q["question"].strip().lower(): q for q in profile.get("qa_bank", [])}
    for f in doc.get("fields", []):
        label = (f.get("label") or "").strip()
        if (f.get("source") in ("user", "approved") and f.get("value")
                and f["kind"] not in ("file",) and label.lower() not in STANDARD_FIELDS
                and len(str(f["value"])) < 600):
            bank[label.lower()] = {"question": label, "answer": f["value"]}
    profile["qa_bank"] = list(bank.values())
    save_profile(profile)


@app.route("/api/jobs/<job_id>/apply/answers", methods=["POST"])
def api_apply_answers(job_id):
    edits = (request.get_json(force=True) or {}).get("answers", {})
    _save_answers(job_id, edits)
    return jsonify({"ok": True})


@app.route("/api/jobs/<job_id>/apply/submit", methods=["POST"])
def api_apply_submit(job_id):
    body = request.get_json(force=True) or {}
    doc = _save_answers(job_id, body.get("answers", {}))
    unresolved = [f["label"] for f in doc.get("fields", [])
                  if f.get("needs_review") or (f.get("required") and f.get("value") in (None, "", []))]
    if unresolved:
        return jsonify({"error": "still needs answers: " + "; ".join(unresolved)}), 400
    if not _set_apply_status(job_id, "submit_requested", ["awaiting_review"]):
        return jsonify({"error": "application isn't awaiting review"}), 409
    if body.get("remember", True):
        _remember_answers(doc)
    return jsonify({"ok": True})


@app.route("/api/jobs/<job_id>/apply/manual", methods=["POST"])
def api_apply_manual(job_id):
    _set_apply_status(job_id, "needs_manual")
    return jsonify({"ok": True})


@app.route("/apply-shot/<job_id>/<name>")
def apply_shot(job_id, name):
    if not re.fullmatch(r"(fill(_\d)?|after_submit)\.png", name) or not re.fullmatch(r"[\w-]+", job_id):
        abort(404)
    return send_from_directory(os.path.join(APPLY_DIR, job_id), name, max_age=0)


@app.route("/health")
def health():
    return jsonify({"ok": True})


ensure_columns()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8012)
