# Dependency Upgrades

Installs are reproducible: a library release must never change behaviour
without a reviewed change in this repository.

## What is pinned

| Layer | Human-edited (ranges) | Enforced lock | Used by |
|---|---|---|---|
| Backend, full (incl. test deps) | `backend/requirements.txt` | `backend/requirements.lock` (exact, with hashes, direct + transitive) | CI, cd-staging smoke check, pip-audit |
| Backend, production image | same file, minus test-only packages | `backend/requirements.runtime.lock` | `backend/Dockerfile` |
| Frontend | `frontend/package.json` | `frontend/package-lock.json` | CI, cd-staging, `frontend/Dockerfile` (all `npm ci`) |

Backend installs use `pip install --require-hashes -r <lock>`, so any
unlisted or altered package fails the install. `sqlalchemy[asyncio]` stays in
`requirements.txt`, so `greenlet` is in both locks.

The backend locks are Linux-only (Python 3.12, the CI runner and the
production image). They cannot be installed natively on Windows or macOS;
use the Docker image or WSL/a Linux container for a local install from the
lock.

## Guards

- CI job "Dependency lock drift" runs `backend/scripts/lock_deps.sh check`
  and fails if `requirements.txt` changed without regenerating the locks.
- `backend/tests/test_dependency_locks.py` fails if a direct requirement is
  missing from the lock, or if code under `app/`, `scripts/` or `alembic/`
  imports a package that is not in `requirements.runtime.lock`.
- The Docker smoke job imports the production scripts inside the built image.

## Upgrading deliberately

Do this in its own PR, never bundled with feature work.

1. Edit the range in `backend/requirements.txt` / `frontend/package.json` only
   if the range itself must change.
2. Regenerate the backend locks with the helper script (needs `uv`; Python
   3.12 target, matching CI and the image). It builds the runtime input
   (`requirements.txt` minus the test-only packages aiosqlite, pytest,
   pytest-asyncio, pdfplumber, PyYAML -- `httpx` is a runtime dependency of
   the Drive backup scripts and stays in) and overwrites both lock files:

   ```
   backend/scripts/lock_deps.sh write                          # keep locked versions
   backend/scripts/lock_deps.sh write --upgrade-package NAME   # move one package
   backend/scripts/lock_deps.sh write --upgrade                # move everything
   ```

   Commit the changed `requirements.lock` and `requirements.runtime.lock`
   together. Frontend: `npm install <pkg>@<version>` or `npm update`,
   committing `package-lock.json`.
3. Read the release notes of every changed package, especially FastAPI,
   Starlette, Pydantic, SQLAlchemy and WeasyPrint (form parsing, validation
   and font output have changed in minor releases before).
4. Let CI run fully (backend, Postgres, frontend) and review the lock diff.
5. Merge only on green CI. If behaviour changes, fix it in the same PR or
   pin back.
