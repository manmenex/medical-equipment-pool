FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

# PR24C's backup/restore engine shells out to the pg_dump and pg_restore
# BINARIES (backend/scripts/backup_postgres.py:114,
# restore_postgres.py:211), and docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md
# section 2 states them as a prerequisite: "on PATH, matching (or compatible
# with) the target PostgreSQL server's major version". PR24D-L3 runs that
# engine INSIDE this image (deployment/local-staging/lib/Backup.ps1 invokes
# `compose run --rm --no-deps backend python scripts/backup_postgres.py`),
# so the prerequisite has to hold HERE -- and it did not. libpq-dev above is
# the client library's HEADERS, for building psycopg; it ships no pg_dump.
# The first real local-staging backup therefore died instantly with
# FileNotFoundError: [Errno 2] No such file or directory: 'pg_dump', which
# also made .\update.ps1 impossible, since its mandatory pre-update backup
# gate can never be satisfied without this.
#
# postgresql-client-16 specifically, and from PGDG rather than Debian:
# bookworm's own `postgresql-client` metapackage is 15, and pg_dump 15
# REFUSES a version 16 server outright ("aborting because of server version
# mismatch"). Every compose file here pins postgres:16-alpine, so plain
# `postgresql-client` would have failed on the same machine for a second,
# more confusing reason. backend/tests/test_pr24d_backup_client_tooling.py
# asserts this major version equals the pinned server's, so bumping the
# server without bumping the client fails CI instead of the next backup.
#
# The .asc key is consumed directly via signed-by (apt >= 2.4 reads
# ASCII-armoured keys), so no gnupg is needed in the image.
RUN install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo "$VERSION_CODENAME")-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
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
RUN grep -vE '^(aiosqlite|pytest|pytest-asyncio|httpx|pdfplumber|PyYAML)([><=~! ]|$)' requirements.txt > requirements.runtime.txt \
    && pip install --no-cache-dir -r requirements.runtime.txt

COPY . .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 127.0.0.1, not `localhost` -- same reasoning as frontend/Dockerfile.
# This probe was never broken, because curl tries every address that
# resolves and so falls back from ::1 to IPv4 on its own. That is curl
# being forgiving, not the address being correct: swapping curl for wget
# would have broken it silently. Naming the address removes the trap.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/v1/health || exit 1

# PR24B (docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §15/§15A):
# exactly 1 worker. app.worker.scheduler starts an in-process
# AsyncIOScheduler per worker/replica with no leader-election guard --
# more than one backend instance running the embedded scheduler
# duplicates the daily 06:00 PM/CAL notification job. This deployment
# invariant ("backend application instances running the embedded
# scheduler must remain exactly 1 until scheduler leadership is
# redesigned") also applies to docker-compose.prod.yml's own
# `replicas` setting and to any managed-platform instance-count
# configuration -- see that file's own comment.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
