#!/usr/bin/env bash
# PR24D-L2 Fix Round 2 (P1-A, §3, §21): CLI-level contract check for the
# migration invocation.
#
# Fix Round 1 shipped `docker compose run --rm --no-build ...`. That flag
# does not exist -- the real CLI answers "unknown flag: --no-build" -- so
# the migration could never have run on any machine. Structural tests did
# not catch it because they only asserted the string the code produced.
# This asks the actual Docker CLI instead.
#
# Deliberately DAEMON-FREE: it only exercises flag parsing and `--help`
# output. It starts no container, builds no image, and touches no
# database. It is NOT evidence of a real migration or installation.
set -uo pipefail

fail=0
note() { printf '%s\n' "$*"; }
check() { if [ "$1" = "0" ]; then note "  OK   $2"; else note "  FAIL $2"; fail=1; fi }

if ! docker compose version >/dev/null 2>&1; then
    note 'docker compose CLI not available -- skipping CLI contract check.'
    exit 0
fi

note "Docker Compose CLI under test: $(docker compose version)"
note ''

help_text="$(docker compose run --help 2>&1)"

# 1. The flag the installer must never use again does not exist.
printf '%s' "$help_text" | grep -q -- '--no-build'
check "$([ $? -ne 0 ] && echo 0 || echo 1)" \
    "'docker compose run' has no --no-build flag (so the installer must not pass it)"

# 2. The flags the installer DOES use are real.
for flag in --rm --no-deps --name; do
    printf '%s' "$help_text" | grep -q -- "$flag"
    check $? "'docker compose run' accepts $flag"
done

# 3. The rejection is reproducible, not just absent from --help. Parsing
#    happens before any daemon call, so this is safe without a daemon.
out="$(docker compose run --rm --no-build --no-deps alpine true 2>&1 || true)"
printf '%s' "$out" | grep -qi 'unknown flag: --no-build'
check $? "passing --no-build is rejected by the CLI as an unknown flag"

# 4. The installer's own migration invocation must not carry it.
repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
ops="$repo_root/deployment/local-staging/lib/Operations.ps1"
# Matches the quoted PowerShell argument form only, so the docstring that
# explains why this flag is forbidden does not trip the check.
grep -q -- "'--no-build'" "$ops"
check "$([ $? -ne 0 ] && echo 0 || echo 1)" "lib/Operations.ps1 does not pass --no-build"
grep -q -- "'--build'" "$ops"
check "$([ $? -ne 0 ] && echo 0 || echo 1)" "lib/Operations.ps1 does not pass --build on migration either"

note ''
if [ "$fail" -ne 0 ]; then
    note 'Compose CLI contract check FAILED.'
    exit 1
fi
note 'Compose CLI contract check passed.'
