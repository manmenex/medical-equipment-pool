# Staging Deployment Runbook — Medical Equipment Pool (Roadmap PR24D)
## คู่มือปฏิบัติการนำระบบขึ้น Staging — ระบบบริหารจัดการเครื่องมือแพทย์ส่วนกลาง

**Status:** Operational execution document for the CI/CD and Staging
deployment capability built in PR24D. Defines the exact build/scan/migrate/
deploy/verify sequence, the immutable-artifact model, and the evidence
template operators use once a real Staging environment exists.

**Authority:** `docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §14–
§21 control the underlying architecture (immutable artifacts, CI/CD staged
pipeline, environment topology, migration deployment procedure, application
rollback). Where this runbook and that design document conflict, the design
document controls. `docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md` governs
backup/restore rehearsal specifically — this document only triggers it once
real Staging exists; it does not redefine it.

**Authoritative baseline this runbook was written against:**
`cd9764ef5ba5e56062ee41266c8d96e50f1152c0` (GitHub PR #132, PR24C — Backup &
Restore, merged).

**Maintainer:** Deployment/technical contact (per
`docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §1's contact matrix — no new role is
introduced here).

---

## 0. อ่านก่อนเริ่มปฏิบัติ (Read this first)

**สิ่งสำคัญที่สุดของเอกสารนี้: แยกให้ชัดระหว่าง "workflow พร้อม deploy" กับ
"มี Staging environment จริงแล้ว" — สองสถานะนี้ไม่เหมือนกัน:**

- PR24D สร้าง *กลไก* (mechanism) สำหรับ build/scan/migrate/deploy/verify และ
  พิสูจน์ว่ากลไกทำงานถูกต้อง ผ่านการรันจริงบน ephemeral CI-provisioned
  PostgreSQL + container บน GitHub Actions runner เท่านั้น
- **ยังไม่มีการเลือก hosting provider จริง** (OD-PR24-1 อนุมัติเฉพาะ
  "สถาปัตยกรรมประเภท" — Managed Application Platform + Managed PostgreSQL —
  ไม่ใช่ผู้ให้บริการรายใดรายหนึ่ง) และ **ยังไม่มีการสร้าง external/paid resource
  ใดๆ** โดย PR24D
- **"CD mechanism proof" ≠ "real Staging environment exists."** ห้ามอ้างว่า
  Staging deployment เกิดขึ้นจริง หรือ real PR24C backup/restore rehearsal
  ผ่านแล้ว จนกว่าจะมี Staging infrastructure จริงและมีการรันตามเอกสารนี้จริง
- Production GO ยังคงถูกบล็อกไว้ตาม Gate A จนกว่าจะมี real Staging deployment
  evidence และ real backup/restore rehearsal evidence (`docs/runbooks/
  PR24_BACKUP_RESTORE_RUNBOOK.md`) ครบถ้วน

---

## 1. Scope

**What this runbook covers:** the sequence to build an immutable, commit-
SHA-tagged application artifact; scan it; migrate a target database; deploy
the artifact; verify it is live and ready; and record evidence — against
Staging, and, once selected, Production. **What it does not cover:** UAT
sign-off (PR24E), Pilot execution (PR24F), Production Go-Live governance
(PR24G), or the AppSheet cutover procedure (`docs/runbooks/
PR23_CUTOVER_RUNBOOK.md`).

**Provider status:** not yet selected. §2 below records the candidates and
trade-offs already documented in the design plan's §6, for the Owner's
reference when this decision is made. Nothing in this runbook or in PR24D's
implementation assumes a specific provider.

---

## 2. Provider selection (OD-PR24-1 architecture class approved; vendor not selected)

Per `docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §28,
OD-PR24-1 approves the architecture **class** — Managed Application
Platform + Managed PostgreSQL (Option A) — not a specific commercial
vendor. Selecting the concrete vendor is a genuine next step, requiring
Owner approval before any paid resource is created. Candidates to evaluate
against the design doc's own §6 criteria (operational complexity, cost
predictability, managed PostgreSQL + PITR support, automatic TLS, secret
store, deploy-from-image support, log streaming, rollback support, Thailand/
region latency and data-residency suitability):

| Dimension | What to confirm before selecting |
|---|---|
| Managed PostgreSQL | Version parity with `postgres:16-alpine` (or documented migration-DDL compatibility), automated backups/PITR, connection limits at ~8-user scale |
| Container/image deploy | Accepts a pre-built, commit-SHA-tagged image (this repository's own build-once model, §5) rather than requiring a git-push-triggered rebuild |
| HTTPS hostname | Provider-managed HTTPS hostname acceptable per OD-PR24-5 — no custom domain required to start |
| Secrets | Environment/secret-store mechanism, not a committed `.env` |
| Region / data residency | Latency to Thailand and any data-residency preference the Owner has |
| Cost | Predictable at ~8-user scale; confirm whether it fits within Owner-approved budget before selection |
| Backup/PITR | Whether the managed PostgreSQL offering's own backup feature can supplement (not replace) the PR24C tooling |

**Do not select or provision a specific provider without recording that
decision explicitly (a new Owner Decision entry in `docs/DECISION_LOG.md`,
mirroring OD-PR24-1's own record) and without explicit Owner approval for
any paid resource.**

---

## 3. Immutable artifact model

**Artifact identity contract (Fix Round 1, independent review, P1-B):**
a Git commit SHA and a registry digest answer two different questions,
and are never treated as interchangeable in this workflow:

| Identity | Answers | Mutable? |
|---|---|---|
| Git commit SHA | "Which source revision produced this build?" | No — a commit SHA itself never changes, but... |
| `<repo>-backend:<sha>` registry **tag** | A traceability alias pointing at *some* build of that source SHA | **Yes** — a registry tag is a movable pointer; re-running the workflow for the same commit (or a moved Dockerfile base-image tag) can push different bytes under the same tag |
| `<repo>-backend@sha256:...` registry **digest** | "Which exact bytes were built, scanned, migrated, deployed, verified, promoted, or rolled back?" | **No** — a digest is a content hash; it can never point at different bytes |

- **Build once:** `backend/Dockerfile` and `frontend/Dockerfile` are built
  exactly once per deployed commit SHA, never rebuilt for a later
  environment promotion.
- **Tag format (traceability alias, not artifact identity):**
  `ghcr.io/<owner>/<repo>-backend:<commit-sha>` and
  `ghcr.io/<owner>/<repo>-frontend:<commit-sha>` — see
  `backend/scripts/cd_lib.py`'s `image_tag()`/`is_valid_commit_sha()`. Never
  `latest`, never a branch name, never a manually rebuilt untraceable
  artifact. Useful for humans locating "the image built from commit X," but
  **no scan, migration, deployment, promotion, or rollback step consumes
  this tag** — see below.
- **Digest (immutable artifact identity):** `.github/workflows/cd-staging.yml`'s
  `build-push-images` job captures the registry digest returned by each
  `docker/build-push-action@v6` build step immediately after it runs, fails
  the job closed if either digest is missing or malformed, and exports
  digest-pinned references (`ghcr.io/<owner>/<repo>-backend@sha256:...`).
  Every downstream step — the blocking Trivy scan, the migration step, the
  running container, and the promotion/rollback contract below — consumes
  only this digest-pinned reference, never the tag, never a re-resolved
  lookup of the tag at a later point in the pipeline.
- **Registry:** GitHub Container Registry (GHCR) — already part of this
  repository's own GitHub organization, not a new external account or paid
  resource.
- **Promotion (digest-pinned):** promoting from Staging to Production means
  redeploying the exact same digest-pinned image references already scanned
  and verified — **not** re-pulling by the commit-SHA tag, and **not**
  rebuilding from the same Git SHA. Release evidence records `source_sha`,
  `backend_image_digest`, and `frontend_image_digest`; Production promotion
  reuses these exact digests unless a genuinely new release is built.
- **Rollback (digest-pinned):** rollback means redeploying the previously
  recorded backend/frontend image **digests** associated with the known-good
  release SHA — never "redeploy the prior SHA tag" as the authoritative
  mechanism, since that tag could since have moved. The commit SHA remains
  supporting traceability; the digest remains the executable artifact
  identity.
- **Why a moved tag is safe:** a workflow re-run for the same commit SHA may
  still update where that SHA's tag points (acceptable — it is a
  traceability alias, not a promise of immutability). This is safe *only*
  because every security/migration/verification operation inside a given
  run captures and uses the digest **that same run produced**, evidence
  records the digest, and future promotion consumes the recorded digest, not
  the tag. This workflow never re-resolves a tag after the initial build.
- **Base-image mutability (not solved by this fix, documented as a known
  limitation):** `backend/Dockerfile`'s `FROM python:3.12-slim` and
  `frontend/Dockerfile`'s `FROM node:22-slim`/`FROM nginx:1.27-alpine` are
  tag-pinned, not digest-pinned — a base image tag can itself move between
  two builds of the identical source SHA, so **reproducible byte-for-byte
  identity across separate builds of the same commit is not guaranteed**.
  The digest-identity fix above solves *release* correctness (the digest
  scanned is provably the digest deployed, within one workflow run); it does
  not claim "same source SHA ⇒ same image digest" across separate runs.
  Pinning Dockerfile base images by digest is a narrower, optional future
  hardening step, not required by the current PR24 design and not
  implemented here to avoid unnecessary scope expansion.

---

## 4. Deployment trigger

`.github/workflows/cd-staging.yml` — `workflow_dispatch` only (manual). Input
`ref`: the exact 40-character commit SHA to deploy; empty defaults to the
trusted branch's current tip. The workflow independently validates (via
`git merge-base --is-ancestor`) that the given ref is actually reachable
from the trusted branch (`claude/medical-equipment-pool-0c7fz0`) before
building anything — an untrusted or unreachable ref is refused, not silently
built.

**Why manual:** per the design plan's own instruction, deployment (even the
CD-mechanism-proof kind this workflow currently performs) remains
operator-triggered while the system is not yet in routine production
delivery — no branch push or PR merge triggers a deploy automatically.

---

## 5. Sequence (what the workflow does, in order)

1. **`resolve-ref`** — validate and resolve the exact commit SHA to deploy.
2. **`build-push-images`** — build backend and frontend images from that
   exact commit, tag by SHA (traceability alias) and push to GHCR, then
   **capture the registry digest** each build returns and construct the
   digest-pinned image references (§3) — failing the job closed if a digest
   is missing or malformed.
3. **`dependency-scan`** — `pip-audit` (backend) and `npm audit` (frontend),
   informational (see §6 for the severity policy). Runs in parallel; does
   not gate `migrate-and-verify`.
4. **`image-scan`** — Trivy scan of both **digest-pinned** images (never
   the mutable SHA tag), **blocking on CRITICAL** findings only
   (`ignore-unfixed: true` — no build is blocked on a vulnerability with no
   available fix). **Fix Round 1: this job has no soft-failure escape
   hatch, and `migrate-and-verify` now structurally depends on it succeeding
   — a CRITICAL finding here stops the pipeline before any migration or
   application start, not merely "best-effort" gates it.**
5. **`migrate-and-verify`** (`needs: image-scan`) — against an ephemeral
   CI-provisioned PostgreSQL service container (never real Staging or
   Production), using only the digest-pinned image reference:
   - Record release evidence (source SHA + both components' tag/digest/ref).
   - Pull the exact scanned backend image **by digest** (no rebuild, no
     re-resolution of the tag).
   - Run `backend/scripts/deploy_migrate.py` — the explicit, separate
     migration step (§7) — against the digest-pinned image.
   - Start the deployed container (digest-pinned image) with
     `ENVIRONMENT=production` (the same configuration flag a real
     Staging/Production deployment uses — see §19 of the design plan,
     "Production-like deployment, same architecture class") and a freshly
     generated, per-run JWT secret.
   - Poll `GET /api/v1/health` for liveness.
   - Run `backend/scripts/staging_smoke_check.py` — the readiness-gated
     post-deploy verification (§8).

**This proves the mechanism. It does not deploy to, or prove the existence
of, real Staging infrastructure** — see §0.

---

## 6. Security scanning policy

| Scan | Tool | Policy |
|---|---|---|
| Backend dependencies | `pip-audit` | Informational (`continue-on-error`) — OSV advisory records do not carry a uniform, filterable severity field; findings are printed in the job log for operator review every run |
| Frontend dependencies | `npm audit` | Informational, same rationale |
| Container images (backend, frontend) | Trivy | **Blocking** on CRITICAL severity, unfixed vulnerabilities excluded (`ignore-unfixed: true`) — HIGH/MEDIUM/LOW reported, not blocking |

**Tightening this policy** (e.g. blocking on HIGH severity once the
dependency baseline is clean, or adding severity filtering to the
dependency scans) is a documented future operational decision, not silently
deferred — record it in `docs/DECISION_LOG.md` if changed.

---

## 7. Migration deployment step

`backend/scripts/deploy_migrate.py`:

```bash
DATABASE_URL=postgresql+asyncpg://<staging-db-credentials> \
python scripts/deploy_migrate.py \
    --target-environment staging \
    --artifact-sha <commit-sha>
```

- Reads `DATABASE_URL` from the environment only — never a CLI argument,
  never logged or echoed (matches `backend/scripts/pg_backup_lib.py`'s own
  non-leak convention).
- Records (never including credentials): target environment, artifact SHA,
  Alembic revision before, migration result, Alembic revision after.
- Runs `alembic upgrade head` as an explicit, separate step — never
  automatically on application boot (unchanged from PR24B).
- **Fails closed:** any failure (unreachable database, non-zero `alembic
  upgrade` exit, or an unverifiable post-migration revision) exits non-zero.
  The deployment must not proceed to the application-rollout step on a
  non-zero exit here.
- Forward-fix is the default response to a failed migration, matching
  `docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §10's own established discipline
  — this script does not implement automatic destructive rollback.

---

## 8. Post-deploy smoke check

`backend/scripts/staging_smoke_check.py`:

```bash
python scripts/staging_smoke_check.py \
    --base-url https://<staging-hostname> \
    --frontend-url https://<staging-hostname> \
    --expected-alembic-revision <revision>
```

Checks, in order: base URL reachable; `GET /api/v1/health` (liveness, HTTP
200); `GET /api/v1/ready` (fail-closed readiness — the actual go/no-go
signal, per §15A of the design plan, HTTP 200 required); frontend serves a
non-trivial body (if `--frontend-url` given); deployed Alembic revision
matches expectation (only if `DATABASE_URL` is also set). **Never performs a
login, a write, or any other business-workflow transaction** — read-only GETs
to fixed diagnostic endpoints only, safe to run repeatedly against a live,
shared Staging environment.

---

## 9. Scheduler single-instance invariant (unchanged from PR24B)

Whatever provider is selected, the deployed backend must run **exactly one**
replica/instance with **exactly one** Uvicorn worker
(`backend/Dockerfile`'s `--workers 1`, matching `docker-compose.prod.yml`'s
`replicas: 1`) until `app/worker/scheduler.py` gains leader election. This
applies to Staging exactly as it applies to Production — do not configure
Staging with multiple replicas "since it's only Staging."

---

## 10. Staging database and Redis

- Staging uses its **own** PostgreSQL database and credentials — never
  Production's. Synthetic/representative data only (never a casual copy of
  real hospital data), per the design plan's §19 environment topology.
- If Redis is retained for Staging, it uses its own separate instance/
  configuration. Redis remains non-critical to readiness (§15A.3) —
  Staging's readiness gate must not be made to depend on Redis either.

---

## 11. Admin bootstrap for Staging

Use `python -m app.scripts.bootstrap_admin` (PR24B) exactly as Production
would — never `app.scripts.seed`'s hardcoded demo account. The generated
password is printed once to the operator's terminal and never committed,
logged, or placed in a CI log.

---

## 12. Rollback

Application rollback = redeploy the previously recorded backend/frontend
image **digests** associated with the known-good release SHA (no rebuild;
see §3's digest-pinned promotion/rollback contract — the commit-SHA tag is
traceability only and must not be treated as the authoritative rollback
mechanism, since it can move). If the failed deployment included a
migration, the prior application version must remain compatible with the
**current** (already migrated) schema — this repository's migrations are
additive-first for exactly this reason (`docs/design/
PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §21). Never automatically
downgrade Alembic schema as part of a rollback.
This is distinct from, and never conflated with, `docs/runbooks/
PR23_CUTOVER_RUNBOOK.md`'s own AppSheet-cutover rollback boundary.

---

## 13. Real Staging rehearsal trigger

Once a real Staging environment exists (provider selected, provisioned,
Owner-approved): run this runbook's §5–§8 sequence against it for real, then
run `docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md`'s backup/restore
rehearsal against that same Staging database. Record both using the
evidence templates in §14 below and in that runbook's own §8 — do not
pre-fill either with PASS before the steps actually run.

---

## 14. Evidence template

Record for every real (non-CI-mechanism-proof) Staging or Production
deployment:

| Field | Value |
|---|---|
| Date/time (UTC) | |
| Operator | |
| Source Git commit SHA | |
| Backend image tag (traceability alias) | |
| Backend image digest | |
| Backend digest-pinned reference | |
| Frontend image tag (traceability alias) | |
| Frontend image digest | |
| Frontend digest-pinned reference | |
| Backend digest scanned (Trivy) | |
| Frontend digest scanned (Trivy) | |
| Trivy result (CRITICAL findings) | |
| Backend digest used for migration | |
| Alembic revision before | |
| Migration result (PASS/FAIL) | |
| Alembic revision after | |
| Backend digest verified (`/api/v1/health`/`/api/v1/ready`) | |
| `/api/v1/health` result | |
| `/api/v1/ready` result | |
| Frontend digest verified (smoke check), where applicable | |
| Frontend smoke result | |
| Backup/restore rehearsal status (if applicable this cycle) | |
| Rollback artifact identified (prior known-good backend/frontend digests) | |
| Notes | |

**Do not pre-fill any field with PASS.** Every field is recorded from an
actual executed step. Digest fields are recorded from the workflow's own
`Record release evidence` step output — never re-typed or re-derived by
the operator.

---

## 15. Failure handling

- **Image build fails:** workflow fails; no image is pushed; no deploy step
  runs.
- **Image scan finds a CRITICAL, fixable vulnerability:** workflow fails
  before the migrate/deploy step; previously deployed versions are
  untouched.
- **Migration fails:** deployment fails closed (§7); the prior deployed
  version keeps serving traffic; forward-fix the migration and retry.
- **Application fails to become live or ready:** the workflow fails at the
  smoke-check step; do not manually mark the deployment successful.
- **Deployed artifact SHA does not match the expected release SHA:** this is
  a traceability failure — do not proceed; re-resolve the correct ref.

---

## 16. Related documents

| Concern | Document |
|---|---|
| Architecture, environment topology, migration/rollback design | `docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §14–§21 |
| Owner Decisions (provider class, network model, RPO/RTO, environments, hostname, support ownership) | `docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §28 |
| Backup/restore rehearsal (triggered from this runbook once Staging is real) | `docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md` |
| AppSheet cutover procedure (T0–T4, distinct from application deployment) | `docs/runbooks/PR23_CUTOVER_RUNBOOK.md` |
| Overall Roadmap status | `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md` |
