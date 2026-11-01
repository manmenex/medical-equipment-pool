#!/usr/bin/env bash
# Starts a throwaway backend for the PR25E E1 browser drills: a fresh SQLite
# file seeded with synthetic fixtures, served by uvicorn on 127.0.0.1:8000.
# SQLite is NOT PostgreSQL evidence; these drills prove browser behaviour
# against the real API, not database concurrency (design section 17).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
backend="$here/../../../backend"
db_dir="${E2E_DB_DIR:-$(mktemp -d)}"
cd "$backend"
export DATABASE_URL="sqlite+aiosqlite:///$db_dir/e2e.db"
export CACHE_ENABLED=false
export DEBUG=false
export ENVIRONMENT=development
py="${PYTHON:-python3}"
"$py" "$here/seed_e2e.py" >/dev/null
exec "$py" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning
