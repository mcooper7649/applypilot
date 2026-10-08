#!/usr/bin/env bash
# Daily scan: pull new remote postings from Adzuna, score them, and tailor
# documents for the good fits. Schedule with cron, e.g. `0 8 * * * ~/applypilot/daily.sh`.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
docker build -t job-bot "$DIR" --quiet
docker run --rm --env-file "$DIR/.env" \
  -v "$DIR/data:/app/data" -v "$DIR/output:/app/output" \
  job-bot 2>&1 | tee -a "$DIR/data/job-bot.log"
# data/latest_results.json now holds the qualified jobs — wire it to your notifier of choice.
