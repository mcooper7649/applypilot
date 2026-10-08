#!/usr/bin/env python3
"""
Apply worker — polls jobs.db and drives a real (headed, under Xvfb) Chromium.

  fill_requested   → open the form, plan answers, fill everything, screenshot,
                     DO NOT submit → awaiting_review
  submit_requested → re-open the form, re-fill with the reviewed answers, verify
                     nothing required is empty or unreviewed, click Submit,
                     confirm → submitted   (or needs_manual / back to review)

Nothing is ever submitted without an explicit approval from the dashboard.
"""
import json
import os
import shutil
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

from config import DB_PATH  # noqa: E402
from db import ensure_columns  # noqa: E402
from profile import load_profile  # noqa: E402
from apply import form, answers  # noqa: E402

SHOTS = Path(DB_PATH).parent / "apply"
POLL_SECONDS = 4
MAX_STEPS = 6


def blocking(f) -> bool:
    return bool(f.get("needs_review")) or (f.get("required") and f.get("value") in (None, "", []))


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def conn():
    c = sqlite3.connect(str(DB_PATH), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def set_state(job_id, status, log=None, fields=None):
    c = conn()
    sets, vals = ["apply_status = ?", "apply_updated = ?"], [status, now()]
    if log is not None:
        sets.append("apply_log = ?"); vals.append("\n".join(log))
    if fields is not None:
        sets.append("apply_fields = ?"); vals.append(json.dumps(fields))
    c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", (*vals, job_id))
    if status == "submitted":
        c.execute("UPDATE jobs SET app_status='applied', applied_at=COALESCE(applied_at, ?) "
                  "WHERE id=?", (now()[:10], job_id))
    c.commit(); c.close()


def claim():
    """Atomically take the next requested job."""
    c = conn()
    r = c.execute("SELECT * FROM jobs WHERE apply_status IN ('fill_requested','submit_requested') "
                  "ORDER BY apply_updated LIMIT 1").fetchone()
    if r:
        nxt = "filling" if r["apply_status"] == "fill_requested" else "submitting"
        cur = c.execute("UPDATE jobs SET apply_status=? WHERE id=? AND apply_status=?",
                        (nxt, r["id"], r["apply_status"]))
        c.commit()
        if not cur.rowcount:
            r = None
    c.close()
    return r


def known_options(row) -> dict:
    """Greenhouse's posting API lists every question's choices; trust it over the DOM."""
    if row["ats"] != "greenhouse" or not row["ats_meta"]:
        return {}
    out = {}
    for q in json.loads(row["ats_meta"]).get("questions", []):
        for fld in q.get("fields", []):
            vals = [v["label"] for v in fld.get("values", []) if v.get("label")]
            if vals:
                out[fld["name"]] = vals
    return out


def upload_copies(row, shot_dir: Path) -> dict:
    """Recruiters see the uploaded filename — use 'First_Last_Resume.pdf', not our internal id."""
    who = "_".join(load_profile().get("name", "Resume").split())
    out = {}
    for kind, src, label in (("resume", row["resume_path"], "Resume"),
                             ("cover_letter", row["cover_letter_path"], "Cover_Letter")):
        if src and Path(src).exists():
            dst = shot_dir / "upload" / f"{who}_{label}.pdf"
            dst.parent.mkdir(exist_ok=True)
            shutil.copyfile(src, dst)
            out[kind] = str(dst)
    return out


def run_job(browser, row):
    job_id, submit = row["id"], row["apply_status"] == "submit_requested"
    log = [f"[{now()}] {'submit' if submit else 'fill'} run started"]
    shot_dir = SHOTS / job_id
    shot_dir.mkdir(parents=True, exist_ok=True)
    prior_doc = json.loads(row["apply_fields"]) if row["apply_fields"] else {}
    prior = {f["key"]: f for f in prior_doc.get("fields", [])}

    resume_data = json.loads(row["resume_json"] or "{}")
    cover_text = resume_data.get("_cover_letter", "")
    files = upload_copies(row, shot_dir)
    job = {"title": row["title"], "company": row["company"], "description": row["description"]}
    url = row["apply_url"] or row["url"]

    ctx = browser.new_context(viewport={"width": 1280, "height": 1000}, locale="en-US")
    page = ctx.new_page()
    try:
        form.open_form(page, url)
        log.append(f"opened {page.url}")
        profile = load_profile()
        known = known_options(row)
        visited, shots = [], []
        outcome = None

        for step in range(1, MAX_STEPS + 1):
            form.dismiss_cookies(page)
            fields = form.extract_fields(page, known)
            log.append(f"step {step}: found {len(fields)} fields")
            if step == 1 and not any(f["kind"] == "text" for f in fields):
                page.screenshot(path=str(shot_dir / "fill_1.png"), full_page=True)
                log.append("no application form found (login wall or unsupported site)")
                set_state(job_id, "needs_manual", log, {**prior_doc, "screenshot": "fill_1.png",
                                                        "screenshots": ["fill_1.png"],
                                                        "page_url": page.url})
                return
            for f in fields:
                f["step"] = step
            fields = answers.plan(fields, job, profile, cover_text, prior)
            for f in fields:
                err = form.fill_field(page, f, f.get("value"), files)
                f["fill_error"] = err
                if err:
                    f["needs_review"] = True
                    log.append(f"  ! {f['label'][:60]}: {err}")
                if submit and f["key"] not in prior:
                    # appeared since your last review (e.g. a later step) — never send unseen answers
                    f["needs_review"] = True
            page.wait_for_timeout(800)
            shot = f"fill_{step}.png"
            page.screenshot(path=str(shot_dir / shot), full_page=True)
            shots.append(shot)
            visited += fields

            nxt, sub = form.find_next(page), form.find_submit(page)
            if not submit:
                if nxt and not sub:
                    log.append("multi-step form: later steps get filled after you approve this one "
                               "(clicking Next sends this page to the employer)")
                outcome = "review"
                break
            if any(blocking(f) for f in fields):
                log.append(f"step {step} needs your answers before continuing")
                outcome = "review"
                break
            if nxt and not sub:
                before = {f["key"] for f in fields}
                nxt.click()
                log.append(f"step {step} approved → clicked '{nxt.inner_text().strip()[:30]}'")
                page.wait_for_timeout(3500)
                after = {f["key"] for f in form.extract_fields(page, known)}
                if after == before:
                    errs = form.visible_errors(page)
                    log.append("form didn't advance: " + ("; ".join(errs) or "no error shown"))
                    outcome = "review"
                    break
                continue
            outcome = "submit"
            break

        # keep reviewed answers for steps we didn't reach this run
        last = max((f["step"] for f in visited), default=0)
        later = [f for f in prior_doc.get("fields", []) if f.get("step", 1) > last]
        doc = {"fields": visited + later, "screenshots": shots, "screenshot": shots[-1],
               "page_url": page.url, "filled_at": now()}

        if outcome != "submit":
            n = sum(blocking(f) for f in doc["fields"])
            log.append(f"waiting for review; {n} field(s) need an answer")
            set_state(job_id, "awaiting_review", log, doc)
            return

        btn = form.find_submit(page)
        if not btn:
            log.append("no submit button found")
            set_state(job_id, "needs_manual", log, doc)
            return
        btn.click()
        log.append(f"clicked '{btn.inner_text().strip()[:30]}'")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(3000)
        page.screenshot(path=str(shot_dir / "after_submit.png"), full_page=True)
        doc["after_screenshot"] = "after_submit.png"
        body = page.inner_text("body")
        if form.SUCCESS_RE.search(body):
            log.append("confirmation detected ✓")
            set_state(job_id, "submitted", log, doc)
        elif form.CAPTCHA_RE.search(body) or page.locator(
                "iframe[src*='recaptcha'][title*='challenge'], iframe[src*='hcaptcha']").count():
            log.append("CAPTCHA challenge — finish this one by hand")
            set_state(job_id, "needs_manual", log, doc)
        else:
            errs = form.visible_errors(page)
            log.append("no confirmation text seen — check the screenshot / your email"
                       + (": " + "; ".join(errs) if errs else ""))
            set_state(job_id, "needs_manual", log, doc)
    finally:
        ctx.close()


def main():
    ensure_columns()
    print(f"[{now()}] apply worker up, db={DB_PATH}", flush=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=os.getenv("HEADLESS") == "1",
                                     args=["--disable-blink-features=AutomationControlled"])
        while True:
            row = claim()
            if not row:
                time.sleep(POLL_SECONDS)
                continue
            print(f"[{now()}] {row['apply_status']} {row['id']} {row['company']}", flush=True)
            try:
                run_job(browser, row)
            except Exception as e:
                traceback.print_exc()
                set_state(row["id"], "failed", [f"[{now()}] {type(e).__name__}: {e}"])


if __name__ == "__main__":
    main()
