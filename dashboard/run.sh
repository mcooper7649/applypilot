#!/usr/bin/env bash
# (Re)start the job-bot dashboard on port 8012.
# Runs ON the job-bot image so it shares the bot's code (WeasyPrint re-render,
# Anthropic SDK for link import). Mounts the whole project at /app.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Ensure the bot image exists / is current (cheap if already built).
docker build -t job-bot "$DIR" --quiet

docker rm -f job-bot-dashboard 2>/dev/null || true
docker run -d --name job-bot-dashboard --restart unless-stopped \
  -p 8012:8012 \
  -w /app \
  -v "$DIR":/app \
  --env-file "$DIR"/.env \
  job-bot python3 dashboard/server.py

echo "job-bot-dashboard up on :8012 (on job-bot image)"
