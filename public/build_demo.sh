#!/usr/bin/env bash
# Regenerate the ApplyPilot walkthrough assets in public/site/demo/ (real run,
# fictional candidate). Costs a few Claude calls.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
ENV=(--env-file .env -e JOBBOT_PROFILE=/app/public/demo/profile.json -v "$DIR":/app -w /app)

docker run --rm "${ENV[@]}" job-bot \
  sh -c 'pip install -q pymupdf >/dev/null 2>&1; python3 public/build_demo.py docs'
docker run --rm "${ENV[@]}" job-bot-apply python3 public/build_demo.py fill

# containers write as root; hand the assets back so git/rsync on the host can manage them
docker run --rm -v "$DIR"/public/site/demo:/d alpine chown -R "$(id -u):$(id -g)" /d
ls -la public/site/demo
