import requests
from config import ADZUNA_APP_ID, ADZUNA_APP_KEY, MIN_SALARY, JOB_ROLES

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/us/search/{page}"
REMOTE_KEYWORDS = {"remote", "work from home", "wfh", "distributed", "anywhere in the us"}
HEADERS = {"Content-Type": "application/json"}

def _is_remote(job: dict) -> bool:
    text = " ".join([
        job.get("title", ""),
        job.get("description", ""),
        job.get("location", {}).get("display_name", ""),
    ]).lower()
    return any(kw in text for kw in REMOTE_KEYWORDS)

def fetch_jobs(pages: int = 2) -> list[dict]:
    all_jobs: list[dict] = []
    seen_ids: set = set()

    for role in JOB_ROLES:
        for page in range(1, pages + 1):
            params = {
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "what": role,
                "results_per_page": 20,
                "full_time": 1,
                "salary_min": MIN_SALARY,
                "sort_by": "date",
            }
            try:
                r = requests.get(
                    ADZUNA_BASE.format(page=page),
                    params=params,
                    headers=HEADERS,
                    timeout=30,
                )
                r.raise_for_status()
            except requests.RequestException as e:
                print(f"[adzuna] error fetching '{role}' page {page}: {e}")
                continue

            for job in r.json().get("results", []):
                jid = str(job.get("id", ""))
                if jid in seen_ids:
                    continue
                if not _is_remote(job):
                    continue
                seen_ids.add(jid)
                all_jobs.append({
                    "id": jid,
                    "title": job.get("title", ""),
                    "company": job.get("company", {}).get("display_name", "Unknown"),
                    "url": job.get("redirect_url", ""),
                    "description": job.get("description", ""),
                    "salary_min": job.get("salary_min"),
                    "salary_max": job.get("salary_max"),
                    "location": job.get("location", {}).get("display_name", ""),
                    "source": "adzuna",
                })

    print(f"[adzuna] fetched {len(all_jobs)} unique remote jobs")
    return all_jobs
