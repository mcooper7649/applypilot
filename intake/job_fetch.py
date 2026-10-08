"""
Resolve a job link into a structured job dict.

Known ATSes (Greenhouse, Lever, Ashby) are read through their public posting
APIs, which give a clean description and the real application URL. Anything
else is fetched as HTML, checked for an embedded ATS link or schema.org
JobPosting JSON-LD, and finally handed to Claude for extraction.
"""
import hashlib
import html as htmlmod
import json
import re
from urllib.parse import urlparse, parse_qs

import requests

from llm import structured, obj, STR, NUM_OR_NULL

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


class FetchError(RuntimeError):
    pass


def job_id_for(url: str) -> str:
    return "m_" + hashlib.sha1(url.strip().encode()).hexdigest()[:12]


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = htmlmod.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def _get(url: str, **kw):
    r = requests.get(url, headers=UA, timeout=25, **kw)
    r.raise_for_status()
    return r


# ── ATS detection ────────────────────────────────────────────────────────────
def detect_ats(url: str) -> tuple[str, dict] | None:
    u = urlparse(url)
    host, parts = u.netloc.lower(), [p for p in u.path.split("/") if p]
    qs = parse_qs(u.query)
    if "greenhouse.io" in host:
        if "for" in qs and "token" in qs:                       # embed/job_app?for=X&token=Y
            return "greenhouse", {"board": qs["for"][0], "id": qs["token"][0]}
        if len(parts) >= 3 and parts[1] == "jobs":
            return "greenhouse", {"board": parts[0], "id": parts[2]}
    if host == "jobs.lever.co" and len(parts) >= 2:
        return "lever", {"company": parts[0], "id": parts[1]}
    if host == "jobs.ashbyhq.com" and len(parts) >= 2:
        return "ashby", {"org": parts[0], "id": parts[1]}
    return None


def _find_embedded_ats(page_url: str, html: str) -> tuple[str, dict] | None:
    """Company career pages often wrap a Greenhouse/Lever/Ashby posting."""
    for m in re.finditer(r"https?://(?:boards|job-boards)\.greenhouse\.io/[^\s\"'<>]+"
                         r"|https?://jobs\.lever\.co/[^\s\"'<>]+"
                         r"|https?://jobs\.ashbyhq\.com/[^\s\"'<>]+", html):
        hit = detect_ats(htmlmod.unescape(m.group(0)))
        if hit:
            return hit
    # ?gh_jid=123 on a company domain + the board token in the embed script
    gh_jid = parse_qs(urlparse(page_url).query).get("gh_jid")
    board = re.search(r"greenhouse\.io/embed/job_board/js\?for=([A-Za-z0-9_-]+)", html)
    if gh_jid and board:
        return "greenhouse", {"board": board.group(1), "id": gh_jid[0]}
    return None


# ── ATS fetchers ─────────────────────────────────────────────────────────────
def _greenhouse(board: str, jid: str) -> dict:
    d = _get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}",
             params={"questions": "true", "pay_transparency": "true"}).json()
    pay = (d.get("pay_input_ranges") or [{}])[0]
    cents = lambda v: v / 100 if v else None                       # noqa: E731
    return {
        "title": d.get("title", ""),
        "company": d.get("company_name") or board.replace("-", " ").title(),
        "location": (d.get("location") or {}).get("name", ""),
        "description": strip_html(htmlmod.unescape(d.get("content", ""))),
        "salary_min": cents(pay.get("min_cents")), "salary_max": cents(pay.get("max_cents")),
        "apply_url": f"https://job-boards.greenhouse.io/{board}/jobs/{jid}",
        "ats": "greenhouse",
        "ats_meta": {"board": board, "id": jid, "questions": d.get("questions", [])},
    }


def _lever(company: str, pid: str) -> dict:
    d = _get(f"https://api.lever.co/v0/postings/{company}/{pid}").json()
    lists = "\n\n".join(f"{l.get('text','')}\n{strip_html(l.get('content',''))}"
                        for l in d.get("lists", []))
    sal = d.get("salaryRange") or {}
    yearly = sal.get("interval") in (None, "per-year-salary")
    return {
        "title": d.get("text", ""),
        "company": company.replace("-", " ").title(),
        "location": (d.get("categories") or {}).get("location", ""),
        "description": "\n\n".join(x for x in (d.get("descriptionPlain"), lists,
                                                d.get("additionalPlain")) if x),
        "salary_min": sal.get("min") if yearly else None,
        "salary_max": sal.get("max") if yearly else None,
        "apply_url": d.get("applyUrl") or f"https://jobs.lever.co/{company}/{pid}/apply",
        "ats": "lever",
        "ats_meta": {"company": company, "id": pid},
    }


def _ashby(org: str, jid: str) -> dict:
    d = _get(f"https://api.ashbyhq.com/posting-api/job-board/{org}",
             params={"includeCompensation": "true"}).json()
    job = next((j for j in d.get("jobs", []) if j.get("id") == jid), None)
    if not job:
        raise FetchError("Ashby posting not found (closed or unlisted?)")
    smin = smax = None
    for comp in (job.get("compensation") or {}).get("summaryComponents", []):
        if comp.get("compensationType") == "Salary":
            smin, smax = comp.get("minValue"), comp.get("maxValue")
    return {
        "title": job.get("title", ""),
        "company": org.replace("-", " ").title(),
        "location": job.get("location", ""),
        "description": job.get("descriptionPlain") or strip_html(job.get("descriptionHtml", "")),
        "salary_min": smin, "salary_max": smax,
        "apply_url": job.get("applyUrl") or f"https://jobs.ashbyhq.com/{org}/{jid}/application",
        "ats": "ashby",
        "ats_meta": {"org": org, "id": jid},
    }


_FETCHERS = {
    "greenhouse": lambda m: _greenhouse(m["board"], m["id"]),
    "lever": lambda m: _lever(m["company"], m["id"]),
    "ashby": lambda m: _ashby(m["org"], m["id"]),
}

# ── Generic pages ────────────────────────────────────────────────────────────
GENERIC_SCHEMA = obj({
    "is_job_posting": {"type": "boolean"},
    "title": STR, "company": STR, "location": STR,
    "salary_min": NUM_OR_NULL, "salary_max": NUM_OR_NULL,
    "description": STR,
})


def _jsonld_posting(html: str) -> dict | None:
    for m in re.finditer(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _generic(url: str, html: str) -> dict:
    ld = _jsonld_posting(html)
    hint = ""
    if ld:
        hint = "schema.org JobPosting found on the page:\n" + json.dumps(ld)[:6000] + "\n\n"
    text = strip_html(html)[:20000]
    d = structured(
        "Extract the job posting from this web page. Use only what the page says; "
        "salaries as annual USD numbers (null if not stated). Put the full role "
        "description, responsibilities and requirements in `description`. If this "
        "isn't a single job posting (login wall, search page, error), set "
        "is_job_posting=false.\n\n" + hint + f"PAGE ({url}):\n{text}",
        GENERIC_SCHEMA, effort="low")
    if not d.pop("is_job_posting"):
        raise FetchError("That page doesn't look like a job posting (login wall or "
                         "JavaScript-only page?). Paste the description instead.")
    return {**d, "apply_url": url, "ats": "other", "ats_meta": {}}


def fetch_job(url: str, pasted_description: str = "") -> dict:
    """Return {title, company, location, description, salary_min/max, apply_url, ats, ats_meta}."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if pasted_description.strip():
        job = _generic(url, pasted_description)
        hit = detect_ats(url)
        if hit:   # keep the ATS so the apply worker knows the form type
            job["ats"], job["ats_meta"] = hit
    else:
        hit = detect_ats(url)
        if not hit:
            try:
                html = _get(url).text
            except requests.RequestException as e:
                raise FetchError(f"Couldn't load the page ({e}). Paste the description instead.")
            hit = _find_embedded_ats(url, html)
            if not hit:
                job = _generic(url, html)
        if hit:
            try:
                job = _FETCHERS[hit[0]](hit[1])
            except requests.RequestException as e:
                raise FetchError(f"{hit[0].title()} API error: {e}")

    if not job.get("description"):
        raise FetchError("No job description found. Paste it instead.")
    job["title"] = (job.get("title") or "").strip()
    job["company"] = (job.get("company") or "").strip()
    job["url"] = url
    job["id"] = job_id_for(url)
    return job
