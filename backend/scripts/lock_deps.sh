#!/usr/bin/env bash
# Regenerate or verify the backend dependency locks (see
# docs/runbooks/DEPENDENCY_UPGRADES.md).
#
#   lock_deps.sh write [uv args]   rewrite requirements.lock and
#                                  requirements.runtime.lock. With no uv args
#                                  versions are kept as locked; pass
#                                  --upgrade or --upgrade-package NAME to move.
#   lock_deps.sh check             fail if the committed locks do not match
#                                  requirements.txt (never upgrades).
#
# Requires uv. The locks target Python 3.12 on Linux (CI and the production
# image); they cannot be installed natively on Windows or macOS.
set -euo pipefail
cd "$(dirname "$0")/.."

mode="${1:?usage: lock_deps.sh write|check [uv args]}"
shift || true

# Test-only packages: excluded from the production image. httpx is NOT here --
# scripts/drive_backup*.py import it at runtime.
TEST_ONLY='^(aiosqlite|pytest|pytest-asyncio|pdfplumber|PyYAML)([><=~! ]|$)'

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

compile() { # <input> <output> [uv args...]
  local in="$1" out="$2"
  shift 2
  uv pip compile "$in" --python-version 3.12 --generate-hashes \
    --no-annotate --no-header -o "$out" "$@" >/dev/null
}

full_header() {
  cat <<'EOF'
# GENERATED FILE -- do not edit by hand. Exact, hash-verified lock of every
# direct and transitive backend dependency, including test dependencies
# (Python 3.12, Linux; used by CI). Regenerate with
# backend/scripts/lock_deps.sh; see docs/runbooks/DEPENDENCY_UPGRADES.md.
# Install with: pip install --require-hashes -r requirements.lock
EOF
}

runtime_header() {
  cat <<'EOF'
# GENERATED FILE -- do not edit by hand. Exact, hash-verified lock of every
# direct and transitive RUNTIME dependency for the production image
# (Python 3.12, Linux): requirements.txt minus the test-only packages
# (aiosqlite, pytest, pytest-asyncio, pdfplumber, PyYAML). Versions are
# constrained to requirements.lock. Regenerate with backend/scripts/lock_deps.sh;
# see docs/runbooks/DEPENDENCY_UPGRADES.md.
# Install with: pip install --require-hashes -r requirements.runtime.lock
EOF
}

grep -vE "$TEST_ONLY" requirements.txt >"$work/runtime.in"

if [ "$mode" = "write" ]; then
  if [ "$#" -gt 0 ]; then
    compile requirements.txt "$work/full.txt" "$@"
  else
    compile requirements.txt "$work/full.txt" -c requirements.lock
  fi
  { full_header; cat "$work/full.txt"; } >"$work/requirements.lock"
  compile "$work/runtime.in" "$work/runtime.txt" -c "$work/requirements.lock"
  { runtime_header; cat "$work/runtime.txt"; } >"$work/requirements.runtime.lock"
  cp "$work/requirements.lock" requirements.lock
  cp "$work/requirements.runtime.lock" requirements.runtime.lock
  echo "locks written"
elif [ "$mode" = "check" ]; then
  compile requirements.txt "$work/full.txt" -c requirements.lock
  compile "$work/runtime.in" "$work/runtime.txt" -c requirements.lock
  status=0
  for pair in "full.txt:requirements.lock" "runtime.txt:requirements.runtime.lock"; do
    if ! diff -u <(grep -v '^#' "${pair#*:}") "$work/${pair%%:*}"; then
      echo "ERROR: ${pair#*:} is out of date; run backend/scripts/lock_deps.sh write" >&2
      status=1
    fi
  done
  exit $status
else
  echo "unknown mode: $mode" >&2
  exit 2
fi
