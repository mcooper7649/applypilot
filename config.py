import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ADZUNA_APP_ID     = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY    = os.getenv("ADZUNA_APP_KEY", "")

MIN_SALARY    = 80_000
MIN_FIT_SCORE = 65

JOB_ROLES = [
    "full stack developer",
    "frontend developer react typescript",
    "systems administrator microsoft",
    "IT administrator intune active directory",
    "IT manager technology",
]

BASE_DIR    = Path(__file__).parent
OUTPUT_DIR  = BASE_DIR / "output"
DB_PATH     = BASE_DIR / "data" / "jobs.db"
