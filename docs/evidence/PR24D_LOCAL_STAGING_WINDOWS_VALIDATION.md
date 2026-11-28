# PR24D — Local Staging/UAT Operational Validation on Real Windows

**Purpose:** Sanitized record of the PR24D-L2/L3 local Staging/UAT deployment
being installed and operated on a real Windows machine with Docker Desktop,
by a real operator, against a real PostgreSQL 16 database.
**Evidence class:** **WINDOWS LOCAL STAGING/UAT** — see §2 for exactly what
this does and does not establish.
**Baseline at completion:** `692f718b6f35e8d4a2871aa4cfc52260833e2274`
**Dates:** 2026-09-12 and 2026-09-13 (UTC timestamps throughout)
**Maintainer:** Documentation/Governance Engineer

This document contains no passwords, no secrets, no connection strings, no
tokens and no hospital data. The database exercised here held one
Administrator account and that operator's own audit rows; **no patient data
and no hospital production records were involved at any point.**

---

## 1. Environment

| | |
|---|---|
| OS | Microsoft Windows 11 Home Single Language, `10.0.22631` |
| Shell | PowerShell **7.6.6** (`pwsh`) |
| Docker Engine | `29.6.1` |
| Docker Compose | `v5.3.0` |
| PostgreSQL (container) | `postgres:16-alpine` — server reported `16.15` |
| PostgreSQL client (backend image) | `pg_dump (PostgreSQL) 16.15 (Debian 16.15-1.pgdg13+2)` |
| Deployment path | `C:\mep\deployment\local-staging` |
| Compose project | `mep-local-staging` |

Stated as a fact about the machine tested, not as a recommendation: Windows 11
**Home** provides no Group Policy management and no domain join. It is an
appropriate host for a Staging/UAT execution mode; it is not a specification
for a hospital production host.

---

## 2. What this evidence does and does not establish

**Establishes.** That the PR24D-L2 installer/operations engine and the PR24C
backup/restore engine work end to end on real Windows + Docker Desktop
hardware: a real install, a real Administrator bootstrap, real LAN access from
a second device, a real `pg_dump` backup, a real `pg_restore` rehearsal into a
disposable database, a real update whose mandatory backup gate was satisfied
by an artifact that update itself produced, and a real Redis-degraded test.

**Does NOT establish, and must not be cited as:**

- **Managed-Staging restore rehearsal — PENDING.** No managed Staging
  environment exists. `cd-staging.yml` has still never been executed. This is
  a LOCAL rehearsal against a container on the operator's own machine.
- **RPO ≤ 1 hour — NOT PROVEN.** No scheduled/automated backup cadence was
  configured or observed. Both backups here were taken manually or by an
  operator-initiated update.
- **RTO — measured but not representative.** The restore completed in 1.1
  seconds against an almost-empty database. That figure says nothing about a
  populated hospital dataset.
- **Production GO — NOT AUTHORIZED.** Nothing in this document is a
  production readiness sign-off.
- **Load, concurrency, or multi-user behaviour — NOT TESTED.** One operator,
  two devices.
- **Destructive uninstall — NOT TESTED.** `.\uninstall.ps1 -RemoveData` was
  never run; no volume was ever removed.

---

## 3. Results by validation section

| § | Item | Result |
|---|---|---|
| 2 | Source at exact baseline, clean tree | **PASS** |
| 3 | Read-only precheck, existing state preserved | **PASS** |
| 4 | Install (resumed from PARTIAL) | **PASS** |
| 5 | Administrator bootstrap | **PASS** — one-time password displayed once, never logged |
| 7 | `status.ps1` + completion metadata | **PASS** |
| 8 | Host browser | **PASS** (one page skipped, see below) |
| 9 | LAN second device | **PASS** |
| 10 | Port / network isolation | **PASS** |
| 11 | stop / start / persistence | **PASS** |
| 12 | Real backup | **PASS** |
| 13 | Real LOCAL restore rehearsal | **PASS** |
| 14 | Live database unchanged after rehearsal | **PASS** |
| 15 | Update, incl. mandatory pre-update backup gate | **PASS** |
| 16 | Redis degraded + recovery | **PASS** |
| 17 | Security checks | **PASS** |
| — | Destructive uninstall | **NOT EXECUTED** (deliberately) |

### 3.1 Install and Administrator bootstrap

Resumed from an existing PARTIAL state rather than a manufactured clean
install; `.env`, the generated secrets and the PostgreSQL volume were all
preserved. The installer logged `Existing .env found; preserving all secrets
and configuration unchanged.` and recreated only the two containers whose
images had changed — `postgres` and `redis` were left running untouched.

Completion metadata was written **after** the Administrator bootstrap
succeeded, in the same second:

```
[bootstrap] Administrator created for employee_code=ADMIN001
            (one-time password shown on console only, never logged).
[install] Administrator bootstrap outcome: Created
{ "InstallCompleted": true,
  "SourceSha": "e2cd4ebd800b303a23bad97b8f058bf16f6ed6d1",
  "InstalledAtUtc": "2026-09-12T17:27:45.4058436Z",
  "LastUpdatedAtUtc": "2026-09-12T17:27:45.4060285Z" }
```

A later re-install on a new baseline correctly reported
`Installation already completed previously; skipping Administrator bootstrap
(backend already has one)` — no second account, no new password.

### 3.2 Host browser and LAN

Dashboard, Equipment List, Reports and Legacy Reconciliation all rendered
while authenticated. **Equipment Detail was SKIPPED** — the database contained
no equipment, so there was no record to open. It is recorded as skipped, not
as passed.

From a second device on the same LAN: the login page loaded, the
Administrator signed in, navigation worked, and `/api/v1/ready` returned its
JSON directly in that device's browser — proving the browser → nginx → `/api/`
proxy → backend → PostgreSQL + Redis path from off-host.

### 3.3 Network isolation

```
frontend   0.0.0.0:80->80/tcp, [::]:80->80/tcp
backend    8000/tcp
postgres   5432/tcp
redis      6379/tcp
```

Only the frontend publishes a port. PostgreSQL and Redis show container ports
with no host mapping — **not reachable from the host or the LAN.**

### 3.4 Backup (§12)

| | First backup | Pre-update backup |
|---|---|---|
| Archive | `mep-postgres-localstaging-20260912T235955Z.dump` | `mep-postgres-localstaging-20260913T073534Z.dump` |
| Size | 150,842 bytes | 150,842 bytes |
| SHA-256 | `b882abe7c458f01e27b599efea6488a3e82d711cef8c18c8cde7383376a7d43b` | `6f0fe124e0635693e885d38fd3d8153e7002aef37816caf221d430d81ab527a4` |
| Alembic revision | `0022_cutover_go_no_go_decision` | `0022_cutover_go_no_go_decision` |
| Elapsed | 1.5 s | 1.5 s |
| Checksum verification | **PASS** | **PASS** |

Retention pruning ran on both occasions and correctly deleted nothing
(`retention_days=30`). The manifest records filename, timestamp, size,
checksum, Alembic revision, database name, host, port and tool version — and
**no credential of any kind**.

### 3.5 LOCAL restore rehearsal (§13, §14)

```
Disposable target: mep_local_restore_rehearsal_20260913t072413z
The live local Staging/UAT database is NOT modified.
[restore] checksum OK
[restore] pg_restore OK
[restore] Alembic revision verified: 0022_cutover_go_no_go_decision
[restore] restored row counts: {'equipment': 0, 'wards': 0, 'users': 1,
                               'borrow_transactions': 0, 'audit_logs': 9}
[restore] elapsed_seconds=1.1
Restore rehearsal: PASS   (total 2.7 s)
Disposable rehearsal database ... dropped.
```

`users: 1` is the Administrator bootstrapped the previous day and
`audit_logs: 9` that operator's own session — a genuine dataset, not an empty
dump. Afterwards the disposable database was gone
(`\l | Select-String rehearsal` returned nothing) and `status.ps1` still
reported `EXISTING_HEALTHY` / `Ready`. **The live database was never touched.**

### 3.6 Update and the mandatory pre-update backup gate (§15)

```
Detected installation state: EXISTING_HEALTHY
[build] backend and frontend images built from current source.
[backup] OK: /mep-backups/mep-postgres-localstaging-20260913T073534Z.dump
[update] Pre-update backup gate satisfied by archive
         mep-postgres-localstaging-20260913T073534Z.dump created by this update run.
[stop-app] Application stopped and verified not running.
[deploy-migrate] alembic_revision_before=0022_cutover_go_no_go_decision
[deploy-migrate] alembic upgrade head: OK
[deploy-migrate] alembic_revision_after=0022_cutover_go_no_go_decision
[deploy-migrate] result=PASS
update.ps1 completed successfully (source_sha=692f718b...)
```

Total elapsed 27 seconds (07:35:26 → 07:35:53 UTC).

The gate was satisfied by a **new** artifact, and this is verifiable rather
than merely asserted: the previous day's archive and this one are byte-for-byte
the same size, yet carry different SHA-256 values, because `pg_dump
--format=custom` embeds its own creation timestamp. The recorded checksum is
the new one. The previous archive remained on disk, untouched and unpruned.

The ordering is the documented one — **backup before anything is stopped** — so
a backup failure would leave a running deployment serving.

### 3.7 Redis degraded (§16)

With only Redis stopped:

```
Redis:       Degraded (stopped) (non-blocking)
State:       EXISTING_HEALTHY
Readiness:   Ready
GET /api/v1/ready -> {"status":"ready","database":"ok","redis":"degraded"}
```

Readiness stayed 200 and reported Redis honestly as `degraded` rather than
claiming `ok`; the deployment state did not drop. After
`docker compose start redis`, `status.ps1` reported `Redis: Healthy
(non-blocking)` again.

Not tested during degradation: browser navigation and re-login. Only the
status and readiness contract were observed.

### 3.8 Security (§17)

- No default credentials; the Administrator password was generated once,
  displayed once, and **never written to any log** (the installer log records
  only that it was shown).
- No secret appears in `logs/install-operations.log`; connection strings are
  redacted at source (`mep_local_staging_user@postgres:5432/...`, password
  never present).
- PostgreSQL and Redis not published to host or LAN (§3.3).
- Windows Firewall: found **disabled on the active profile before validation
  began** — a pre-existing condition, not created by this exercise. It was
  **enabled** during validation, and LAN access continued to work through a
  single minimum inbound rule (TCP 80, Private profile only). The firewall was
  **not** disabled to make any test pass.
- `COOKIE_SECURE=false` applies to this trusted local HTTP execution mode
  only; the production default is unchanged.

---

## 4. Defects found by this validation

Five findings, none of which CI or the unit suites could see, because in every
case **the thing that shipped had never been executed in the form it ships**.

| # | Defect | Why the existing tests missed it | Resolution |
|---|---|---|---|
| 1 | `install.ps1` crashed with `The property 'Count' cannot be found on this object` — PowerShell unrolls an empty array to `$null` | All 13 behavior tests passed `-SkipPrerequisites`, so the crashing branch had never once been executed | PR **#138** (`e3250091`) |
| 2 | Frontend `HEALTHCHECK` probed `http://localhost/`, which resolved to `::1`; nginx listens on IPv4 only and BusyBox `wget` does not fall back. `up -d --wait` then aborted the install before the Administrator bootstrap | No CI job ran the image or read its container health; the "Frontend build" job only compiles the SPA | PR **#139** (`e2cd4eb`) |
| 3 | The backend image had no `pg_dump`: `libpq-dev` ships headers, not binaries. Backup failed, restore would have failed identically, and `update.ps1` was impossible because its backup gate has no bypass | `backend-postgres-tests` runs a real `pg_dump` round-trip — on the **runner's** PATH, where a client is preinstalled. The scripts were covered; the image never was | PR **#140** (`b03c146`) |
| 4 | The restore rehearsal created one database and connected to another: `CREATE DATABASE` is an unquoted identifier, which PostgreSQL folds to lower case, while the connection URL is not folded. The timestamp carried an uppercase `T` and `Z` | The behavior suite mocks Docker, so nothing folds anything, and its assertions matched only the name **prefix**. The target URL travels by environment-variable name, so the one string that had to match was the one string no test could see | PR **#141** (`692f718`) |
| 5 | Running the scripts under **Windows PowerShell 5.1** turns `docker compose`'s ordinary stderr progress line into a terminating error — `ERROR:  Container mep-local-staging-postgres-1 Running`, which is not an error at all | No script declares `#Requires -Version`, so nothing warns the operator | **OPEN** — see §5 |

Each of #1–#4 shipped with a regression test that executes the real thing: a
CI job that runs the frontend image and reads its health status, a CI step
that takes a real backup with PR24C's engine inside the built backend image,
and a PowerShell assertion that compares the created database name — lower-cased
the way a real server stores it — against the name in the connection string.

---

## 5. Open items and follow-ups

- **`#Requires -Version 7.0` is not declared by any script.** Finding #5 cost
  real operator time to diagnose. A one-line declaration per entry script
  would turn a baffling error into a clear instruction. Deliberately not fixed
  in this round (the validation brief scoped Windows PowerShell 5.1 out);
  recommended as a small, separate PR.
- **`$IsWindows` under `Set-StrictMode`** in `lib/Backup.ps1` remains
  incompatible with Windows PowerShell 5.1. Same follow-up.
- **No self-service password change exists.** Changing any password requires
  an Administrator calling `PATCH /api/v1/users/{id}`, which asks for no
  current password and enforces no complexity rule. Out of scope for PR24D;
  worth an Owner decision before real users are onboarded.
- **Equipment Detail page unverified** — no equipment records existed.
- **Second-device browser behaviour during Redis degradation** unverified.

---

## 6. Classification summary

| Claim | Status |
|---|---|
| Windows Local Staging/UAT install and operation | **PASS** |
| Local backup | **PASS** |
| LOCAL REHEARSAL restore | **PASS** |
| Update with mandatory verified pre-update backup | **PASS** |
| Managed-Staging rehearsal | **PENDING** |
| RPO ≤ 1 hour | **NOT PROVEN** |
| RTO target ≤ 4 h (OD-PR24-3) | Measured 1.1 s on an almost-empty database — **not representative** |
| Production GO | **NOT AUTHORIZED** |
| PR24E | **NOT STARTED** |
| Cloud resources provisioned | **NONE** |
