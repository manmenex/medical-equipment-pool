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

## Upgrading deliberately

Do this in its own PR, never bundled with feature work.

1. Edit the range in `backend/requirements.txt` / `frontend/package.json` only
   if the range itself must change.
2. Regenerate the backend locks (Python 3.12, matching CI and the image).
   Use `--upgrade-package <name>` to move one package, or `--upgrade` for all:

   ```
   cd backend
   uv pip compile requirements.txt --python-version 3.12 --generate-hashes \
     --no-annotate --no-header -o /tmp/full.txt
   # runtime set = requirements.txt without aiosqlite, pytest, pytest-asyncio,
   # httpx, pdfplumber, PyYAML
   uv pip compile runtime.in -c requirements.lock --python-version 3.12 \
     --generate-hashes --no-annotate --no-header -o /tmp/runtime.txt
   ```

   Put the comment header from the existing lock files back on top of each
   result (`requirements.lock`, `requirements.runtime.lock`).
   Frontend: `npm install <pkg>@<version>` or `npm update`, committing
   `package-lock.json`.
3. Read the release notes of every changed package, especially FastAPI,
   Starlette, Pydantic, SQLAlchemy and WeasyPrint (form parsing, validation
   and font output have changed in minor releases before).
4. Let CI run fully (backend, Postgres, frontend) and review the lock diff.
5. Merge only on green CI. If behaviour changes, fix it in the same PR or
   pin back.
