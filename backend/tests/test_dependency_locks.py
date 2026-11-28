"""Guards for the dependency lock files (docs/runbooks/DEPENDENCY_UPGRADES.md).

* every direct requirement appears in requirements.lock;
* every third-party package imported by code that ships in the production
  image (app/, scripts/, alembic/) is in requirements.runtime.lock, so a
  runtime import can never be "test-only" (httpx once was, which broke the
  Drive backup script in production).
"""

from __future__ import annotations

import ast
import re
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

# Run only in CI / by developers, never inside the production container.
CI_ONLY_SCRIPTS = {"ci_shard_gate.py", "postgres_ci_gate.py"}
LOCAL_PACKAGES = {"app", "scripts", "alembic_local", "tests"}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _names(path: Path, pattern: str) -> set[str]:
    found = set()
    for line in path.read_text().splitlines():
        m = re.match(pattern, line)
        if m:
            found.add(_norm(m.group(1)))
    return found


def _direct_requirements() -> set[str]:
    return _names(BACKEND / "requirements.txt", r"([A-Za-z0-9][A-Za-z0-9._-]*)")


def _locked(lock: str) -> set[str]:
    return _names(BACKEND / lock, r"([A-Za-z0-9][A-Za-z0-9._-]*)==")


def test_every_direct_requirement_is_in_the_full_lock():
    missing = _direct_requirements() - _locked("requirements.lock")
    assert not missing, f"not in requirements.lock: {sorted(missing)}"


def test_runtime_lock_is_subset_of_full_lock():
    assert _locked("requirements.runtime.lock") <= _locked("requirements.lock")


def test_sqlalchemy_asyncio_extra_keeps_greenlet_locked():
    assert "greenlet" in _locked("requirements.runtime.lock")


def _runtime_files() -> list[Path]:
    files = []
    for sub in ("app", "scripts", "alembic"):
        for f in (BACKEND / sub).rglob("*.py"):
            if f.name in CI_ONLY_SCRIPTS:
                continue
            files.append(f)
    return files


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def test_runtime_imports_are_covered_by_the_runtime_lock():
    dist_map = packages_distributions()
    runtime = _locked("requirements.runtime.lock")
    problems = []
    for f in _runtime_files():
        for mod in _top_level_imports(f):
            if mod in sys.stdlib_module_names or mod in LOCAL_PACKAGES or mod == "__future__":
                continue
            if (BACKEND / mod).exists() or (BACKEND / f"{mod}.py").exists():
                continue  # first-party top-level module/package
            dists = {_norm(d) for d in dist_map.get(mod, [])}
            if not dists:
                problems.append(f"{f.relative_to(BACKEND)}: '{mod}' is not an installed distribution")
            elif not dists & runtime:
                problems.append(
                    f"{f.relative_to(BACKEND)}: '{mod}' (from {sorted(dists)}) is not in requirements.runtime.lock"
                )
    assert not problems, "\n".join(sorted(problems))


@pytest.mark.parametrize("lock", ["requirements.lock", "requirements.runtime.lock"])
def test_lock_entries_are_hash_pinned(lock):
    text = (BACKEND / lock).read_text()
    entries = re.findall(r"^[A-Za-z0-9][^\s=]*==\S+ \\\n(?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+", text, re.M)
    assert len(entries) == len(_locked(lock))
