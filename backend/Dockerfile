FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Roadmap PR18D review 4838921407 round 2 (H3): requirements.txt stays a
# single file (no new dependency-file hierarchy, per the approved PR18D
# plan) -- but pdfplumber and the other test-only packages (see
# requirements.txt's own "testing / local sqlite fallback" comment) must
# never ship in the production image. This filters them out by name before
# install; CI's backend-tests/backend-postgres-tests jobs still
# `pip install -r requirements.txt` directly (the full file, unfiltered) on
# the runner, so pytest continues to see every test dependency there.
RUN grep -vE '^(aiosqlite|pytest|pytest-asyncio|httpx|pdfplumber)([><=~! ]|$)' requirements.txt > requirements.runtime.txt \
    && pip install --no-cache-dir -r requirements.runtime.txt

COPY . .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
