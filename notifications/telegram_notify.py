"""
Writes job results to a JSON file.
Delivery (Telegram, email, ...) is left to whatever reads data/latest_results.json.
"""

import json
from datetime import datetime
from pathlib import Path

RESULTS_FILE = Path(__file__).parent.parent / "data" / "latest_results.json"

def write_results(qualified: list[dict], total_new: int) -> None:
    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "total_new_seen": total_new,
        "qualified_count": len(qualified),
        "jobs": [
            {
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "fit_score": j.get("fit_score", 0),
                "salary_min": j.get("salary_min"),
                "salary_max": j.get("salary_max"),
                "url": j.get("url", ""),
                "match_reason": j.get("score_data", {}).get("match_reason", ""),
                "matched_skills": j.get("score_data", {}).get("matched_skills", []),
                "resume_path": j.get("resume_path", ""),
                "cover_letter_path": j.get("cover_letter_path", ""),
            }
            for j in qualified
        ],
    }
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(payload, indent=2))
    print(f"[notify] Results written to {RESULTS_FILE}")
