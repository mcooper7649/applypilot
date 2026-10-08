#!/usr/bin/env bash
# (Re)start the ApplyPilot public API on :8041. Only public/ and data/ (read-only)
# are mounted, so this container can't touch the dashboard or the profile.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"

docker rm -f applypilot-public 2>/dev/null || true
docker run -d --name applypilot-public --restart unless-stopped \
  -p 8041:8041 \
  --read-only --tmpfs /tmp \
  -v "$DIR"/public:/app:ro \
  -v "$DIR"/data:/data:ro \
  -w /app \
  job-bot python3 server.py

echo "applypilot-public up on :8041"
