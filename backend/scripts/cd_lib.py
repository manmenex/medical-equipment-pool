"""PR24D: small, pure, independently-testable helpers shared by the
Staging CD workflow (`.github/workflows/cd-staging.yml`) and its
scripts -- kept separate from any live CI/registry/network call, per
the same "pure logic first" convention `backend/scripts/pg_backup_lib.py`
established for PR24C.
"""

from __future__ import annotations

import re

# A full, lowercase Git commit SHA -- the only ref form this repository's
# immutable-artifact model accepts as a deployment target (docs/design/
# PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md §18/§21/§35: artifact
# identity must be traceable to one exact commit, never a branch name or
# "latest").
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def is_valid_commit_sha(value: str) -> bool:
    """True only for a full 40-character lowercase hex Git commit SHA.
    Used to validate a workflow_dispatch input before it is ever
    interpolated into a shell command or image tag -- rejects branch
    names, `HEAD`, `latest`, short SHAs, and anything else that is not
    itself an unambiguous, immutable commit identity."""
    return bool(_COMMIT_SHA_RE.match(value))


def image_tag(registry: str, image_repository: str, component: str, sha: str) -> str:
    """Build a fully-qualified, commit-SHA-tagged image reference, e.g.
    `ghcr.io/owner/repo-backend:0754c8f3193de5db33645ff6af939d888f748901`.
    Never accepts or produces a `latest`/mutable tag -- see
    `is_valid_commit_sha`, which callers must check before calling this."""
    if not is_valid_commit_sha(sha):
        raise ValueError(f"refusing to build an image tag from a non-commit-SHA value: {sha!r}")
    if not component:
        raise ValueError("component must be a non-empty string (e.g. 'backend', 'frontend')")
    return f"{registry}/{image_repository}-{component}:{sha}"
