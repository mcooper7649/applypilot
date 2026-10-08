# Apply worker: Playwright + Chromium, run headed under Xvfb (headless browsers
# trip bot checks on ATS forms far more often).
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

RUN pip install --no-cache-dir playwright==1.49.0 "anthropic>=0.105" requests python-dotenv

WORKDIR /app
ENV DISPLAY=:99 PYTHONUNBUFFERED=1
# xvfb-run hangs as PID 1 (it waits on a signal that never arrives), so start
# Xvfb directly.
CMD ["sh", "-c", "rm -f /tmp/.X99-lock; Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp & sleep 1; exec python3 apply/worker.py"]
