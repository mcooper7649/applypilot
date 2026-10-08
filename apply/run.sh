#!/usr/bin/env bash
# (Re)start the apply worker. Mounts the whole project like the dashboard so it
# shares jobs.db, profile.json, the tailored PDFs and the code.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"

docker build -t job-bot-apply -f "$DIR"/apply/Dockerfile "$DIR"/apply --quiet

docker rm -f job-bot-apply 2>/dev/null || true
docker run -d --name job-bot-apply --restart unless-stopped --init \
  --shm-size=1g \
  -w /app \
  -v "$DIR":/app \
  --env-file "$DIR"/.env \
  job-bot-apply

echo "job-bot-apply worker up"
