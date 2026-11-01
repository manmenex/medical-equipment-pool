# Backup / Restore Runbook — Medical Equipment Pool (Roadmap PR24C)
## คู่มือปฏิบัติการสำรองข้อมูลและกู้คืนข้อมูล — ระบบบริหารจัดการเครื่องมือแพทย์ส่วนกลาง

> **Note (Owner decision, 2026-10-13): Production runs on the department host.**
> Production is a department PC (Windows 11 Pro, Docker), not a managed cloud
> platform; see the "Local Production on the department host" entry in
> `docs/DECISION_LOG.md` and Roadmap PR25A-E. This revises OD-PR24-1.
>
> What this changes in this runbook: there is no managed PostgreSQL and no
> provider PITR; `pg_dump` backups (this tooling) are the only backup
> mechanism, taken hourly to keep RPO <= 1h. Each hourly backup is also copied
> off the host to the department's Google Drive, with restore-from-Drive onto
> any Docker-capable PC as the recovery path. **That upload is built (Roadmap
> PR25A) and documented in section 12.** It has been verified against mocked
> Google endpoints only; the first real consent, upload and restore-anywhere
> drill on the department host are still to be performed and recorded.

**Status:** Operational execution document for the PostgreSQL backup/restore
capability built in PR24C. Defines the exact commands, safety guards, and
evidence template operators use for the real backup/restore rehearsal
required before Production GO.

**Authority:** `docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §11
controls the underlying design and the Owner-approved RPO/RTO/retention
targets (OD-PR24-3, §28). Where this runbook and that design document
conflict, the design document controls. `docs/runbooks/PR23_CUTOVER_RUNBOOK.md`
§17 defines the evidence-slot fields this runbook's rehearsal record uses —
this document does not duplicate that template, it defines what must be true
before that template's fields can honestly be filled in.

**Authoritative baseline this runbook was written against:**
`d4a40349f62d76d129dcc6f1feea3e7e8fc8f28d` (GitHub PR #131, PR24B — Deployment
Foundation, merged).

**Maintainer:** Database/backup contact (per
`docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §1's contact matrix — no new role is
introduced here).

---

## 0. อ่านก่อนเริ่มปฏิบัติ (Read this first)

**การมีอยู่ของ script เหล่านี้ในรีโพซิทอรี ไม่ได้แปลว่ามีการทดสอบ backup/restore
จริงบน Staging เกิดขึ้นแล้ว:**

- PR24C สร้าง *เครื่องมือ* (tooling) สำหรับ backup/restore และพิสูจน์ว่าเครื่องมือ
  ทำงานถูกต้องผ่าน CI (ฐานข้อมูลทดสอบชั่วคราว) เท่านั้น
- **การซ้อมจริง (real rehearsal) บน Staging-class infrastructure ยังไม่เกิดขึ้น**
  จนกว่า PR24D จะสร้าง Staging environment จริง แล้วมีการรันขั้นตอนในเอกสารนี้จริง
- **"CI proves tooling. Staging rehearsal proves operational readiness."**
  สองสิ่งนี้ไม่เหมือนกัน — ห้ามอ้างว่า Production GO backup gate ผ่านแล้ว
  จนกว่าจะมีหลักฐานการซ้อมจริงตามแบบฟอร์มใน §8 ของเอกสารนี้
- **Production GO ยังคงถูกบล็อกไว้** ตาม Gate A / `docs/runbooks/
  PR23_CUTOVER_RUNBOOK.md` §16/§17 จนกว่าจะมีหลักฐานการกู้คืนข้อมูลจริงที่
  พิสูจน์ว่าเป็นไปตามเป้าหมาย RTO ที่ Owner อนุมัติ

---

## 1. ขอบเขต (Scope)

**What is backed up:** the application PostgreSQL database in full — this is
the complete backup. All persisted application state, including
`import_source_blobs`'s binary content, lives in PostgreSQL; there is no
separate object-storage backup stream (`docs/design/
PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §12).

**Owner-approved targets (OD-PR24-3, resolved, do not reopen):**

| Target | Value |
|---|---|
| RPO (Recovery Point Objective) | ≤ 1 hour |
| RTO (Recovery Time Objective) | ≤ 4 hours |
| Backup retention | 30 days |

These are targets, not a claim that they are already met. Production GO
remains blocked until a real rehearsal demonstrates the restore procedure
meets the RTO target.

**Backup method:** `pg_dump --format=custom` (logical, transactionally
consistent via PostgreSQL's own snapshot semantics — no raw file copy, no
`tar`ing a live data directory, no pausing application writes).

**Provider compatibility (OD-PR24-1):** the tooling assumes only an ordinary
application/operator PostgreSQL credential with backup/restore privilege —
never root shell access, filesystem-level access, or PostgreSQL superuser.
The earlier idea that a managed provider's backup/PITR might replace this
tooling no longer applies (department host, 2026-10-13): this tooling is the
backup mechanism.

---

## 2. ก่อนเริ่ม (Prerequisites)

- `pg_dump` / `pg_restore` on `PATH`, matching (or compatible with) the
  target PostgreSQL server's major version. In the PR24D-L3 local
  Staging/UAT mode this prerequisite applies to the **backend image**, not
  to the operator's Windows host: `.\backup.ps1` and `.\restore.ps1` run
  the engine inside that container. `backend/Dockerfile` installs
  `postgresql-client-16` for exactly this reason, and CI's
  `backend-backup-tooling-smoke-test` job takes a real backup inside the
  built image to prove it.
- A `DATABASE_URL` (or equivalent connection string) with backup privilege
  on the source database.
- A **separate, disposable, non-production** PostgreSQL database to restore
  into — created and destroyed for each rehearsal, never the Pilot or
  Production database.
- This repository checked out at the commit being backed up (for
  `--baseline-sha`), if recording that provenance is desired.

---

## 3. สำรองข้อมูล (Backup)

```bash
cd backend
python scripts/backup_postgres.py \
    --database-url "$DATABASE_URL" \
    --environment production \
    --output-dir /path/to/backup/storage \
    --baseline-sha "$(git rev-parse HEAD)"
```

Produces two files under `--output-dir`:

- `mep-postgres-<environment>-<UTCTIMESTAMP>.dump` — the `pg_dump
  --format=custom` artifact.
- `mep-postgres-<environment>-<UTCTIMESTAMP>.dump.manifest.json` — a sidecar
  manifest: filename, `created_at`, environment, baseline SHA, the source
  database's Alembic revision at backup time, file size, SHA-256 checksum,
  and the `pg_dump` tool/version used.

**On failure:** the script exits non-zero, prints the error (never the
database password or full `DATABASE_URL`), writes no manifest, and leaves
any previous successful backups untouched.

**Never commit backup files to Git.** `/backups/` is already excluded via
`.gitignore` at the repository root.

**Encryption at rest:** required for any location backups are actually
stored. On the department host, use the host's disk encryption (and Google Drive's
storage encryption for the off-host copy, section 12); for interim manual/local rehearsal artifacts, use
your platform's own disk/volume encryption — this tooling does not implement
custom encryption, and none should be invented here.

---

## 4. ตรวจสอบ Checksum (Checksum verification)

`restore_postgres.py` (§5) verifies the SHA-256 checksum recorded in the
manifest against the actual backup file automatically, and refuses to
restore on any mismatch — this is not a separate manual step.

---

## 5. กู้คืนข้อมูล — เพื่อการซ้อม (Restore, for rehearsal)

```bash
cd backend
python scripts/restore_postgres.py \
    --backup-file /path/to/backup/storage/mep-postgres-production-20260828T120000Z.dump \
    --target-database-url "$RESTORE_TARGET_DATABASE_URL" \
    --target-environment staging \
    --source-database-url "$DATABASE_URL"
```

`--source-database-url` is optional. The backup manifest always supplies the
source database's identity (host/port/database name) for restore-target
safety — this flag does **not** enable or disable that protection. If given,
it is used only for additional live source verification (row-count
comparison), and it must agree with the manifest's recorded source identity
or the restore is refused before any destructive action.

**Restore target protection — no normal command path restores over
Production:**

- `--target-database-url` is **required**, with no default.
- `--target-environment` is **required** and refused outright if it equals
  `production` (case-insensitive) — there is no `--allow-production-restore`
  flag anywhere in this tooling, and none should be added.
- The target must be a physically different database (host+port+database
  name, ignoring credentials) than the source database recorded in the
  backup manifest — enforced **unconditionally**, whether or not
  `--source-database-url` is supplied. Fix Round 1 (PR #132 independent
  review) closed a gap where this check was previously skipped if the
  operator omitted that optional flag.
- The target database must be empty (no existing tables) unless
  `--force-non-empty-target` is passed — an extra guard beyond what a
  rehearsal normally needs to override. This flag only ever bypasses the
  empty-target check; it never bypasses the Production or same-source
  guards above.

**What the script verifies, in order:**

1. Backup checksum matches the manifest (hard fail on mismatch — never
   restores a corrupted/tampered artifact).
2. Restore-target guard (above) — using the source identity derived from the
   manifest, unconditionally.
3. If `--source-database-url` was given, it is checked against the
   manifest's recorded source identity (fail closed on mismatch) before it
   is used for any live verification.
4. `pg_restore` completes successfully.
5. The restored database's `alembic_version` matches the manifest's recorded
   revision — proving restore *fidelity*, before any question of running
   `alembic upgrade` (deliberately not run automatically; that is a separate,
   later step if the restored instance is ever used beyond verification).
6. Representative table row counts (`equipment`, `wards`, `users`,
   `borrow_transactions`, `audit_logs`) — diffed against the source if
   `--source-database-url` was given.

**On any verification failure:** the script exits non-zero and reports which
check failed. It never mutates the source database, and never silently
reports PASS.

---

## 6. หลักฐาน RPO (RPO evidence)

RPO ≤ 1 hour means the backup mechanism must be capable of producing a
recoverable backup at least hourly (on the department host there is no provider-managed PITR
alternative). Record, at the time of each rehearsal or Production readiness review:

- Backup schedule/interval actually configured (e.g. "hourly, via a scheduled
  task invoking `backup_postgres.py`").
- Timestamp of the most recent successful backup.
- Alerting/failure behavior if a scheduled backup does not complete
  successfully (a silent backup failure defeats the entire design — see
  `docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §21).

A single successful restore rehearsal does **not**, by itself, prove RPO —
RPO is a property of the *backup schedule's* reliability, not of one restore.

**Local Staging/UAT (PR24D).** The schedule is registered with Windows Task
Scheduler by `.\schedule-backup.ps1 -Install`, which runs the existing
`.\backup.ps1` every hour. Running `.\schedule-backup.ps1` with no arguments
reports whether a schedule exists, when it last ran, and whether that run
**succeeded** — a registered task that fails every hour is not backup
coverage, and is reported as a failure rather than as a green tick.

Two limitations to record honestly alongside any RPO claim:

- (PR25A) The task is registered with the Windows account's password and runs
  whether or not anyone is logged in, at :15 past each hour. It still needs
  Docker Desktop's engine running, which starts when that account signs in at
  boot: **no backup runs while the machine is off or Docker Desktop is not
  running.** See section 12.4.
- The off-host copy can lag the local one (Drive or the network is down). The
  RPO claim for a total loss of the host is the age of the newest *uploaded*
  backup, shown by `.\drive-backup.ps1 -Status`, not of the newest local one.
- Registering the schedule does not by itself prove an RPO. The claim needs
  the schedule *observed succeeding over time* — which is an operational
  observation, not a code change.

---

## 7. หลักฐาน RTO (RTO evidence)

`restore_postgres.py` prints `elapsed_seconds` — wall-clock time from the
start of the restore script's execution to completed, verified restore.
Record this value and compare it against the ≤ 4 hour target. If substantial
manual steps happen *outside* the script (e.g. provisioning the disposable
target database, retrieving the backup artifact from remote storage), time
those too and include them in the recorded elapsed time — do not report only
the in-script `pg_restore` runtime if real recovery would require more.

---

## 8. แบบบันทึกหลักฐานการซ้อม (Rehearsal evidence record)

ห้ามกรอกค่า PASS ล่วงหน้าหรือกรอกโดยไม่มีการซ้อมจริงเกิดขึ้น — ช่องนี้มีไว้
สำหรับบันทึกผลจริงเท่านั้น (ตามหลักการเดียวกับ `docs/runbooks/
PR23_CUTOVER_RUNBOOK.md` §17):

```
== Backup ==
วันที่/เวลา (UTC):                        __________________
Environment ที่สำรอง:                     __________________
Baseline SHA:                            __________________
Alembic revision:                        __________________
ชื่อไฟล์ backup:                          __________________
Checksum (SHA-256):                      __________________
ผลการสำรอง (PASS/FAIL):                   __________________

== Restore ==
Target environment:                      __________________
เวลาเริ่ม (UTC):                          __________________
เวลาสิ้นสุด (UTC):                        __________________
ระยะเวลาที่ใช้ (elapsed):                  __________________
Checksum ตรวจสอบผ่านหรือไม่:               __________________
ผล pg_restore:                           __________________
Alembic revision ตรงกันหรือไม่:            __________________
ผลตรวจสอบจำนวนแถว (row count):             __________________
ผลตรวจสอบ readiness/application:          __________________
RTO <= 4 ชม. ผ่านหรือไม่ (PASS/FAIL):       __________________

== RPO ==
รอบการสำรองข้อมูล/การตั้งค่า:               __________________
อายุของ backup ล่าสุดที่สำเร็จ:              __________________
RPO <= 1 ชม. ผ่านหรือไม่ (PASS/FAIL):       __________________

ผู้รับผิดชอบ (Primary Technical/Support/Incident Owner, OD-PR24-6): __________________
```

**สถานะปัจจุบัน (as of this baseline): ยังไม่มีการซ้อมจริงบน Staging — ห้ามอ้างว่า
Production GO backup gate ผ่านแล้ว จนกว่าจะมีการกรอกแบบฟอร์มนี้ด้วยหลักฐานจริง**
หลังจาก PR24D สร้าง Staging environment และมีการรันการซ้อมจริงตามขั้นตอนใน
เอกสารนี้

---

## 9. Retention / การลบ backup เก่า

Retention เป็นแบบ **tiered** เพราะ backup รายชั่วโมงกับหน้าต่าง 30 วันแบบเดิม
จะเก็บไฟล์ไว้ 720 ไฟล์ — ไม่เป็นไรตอนฐานข้อมูลยังเล็ก แต่เมื่อข้อมูลจริงโตถึงระดับ
50MB จะกินพื้นที่ราว 36GB

| ช่วงอายุ | เก็บอะไร |
|---|---|
| ใหม่กว่า 48 ชั่วโมง | **เก็บทุกไฟล์** — นี่คือช่วงที่ทำให้ RPO ต่ำกว่า 1 ชั่วโมงเป็นจริง |
| 48 ชั่วโมง – 30 วัน | เก็บไฟล์ **ล่าสุดของแต่ละวัน (UTC)** ที่เหลือลบ |
| เก่ากว่า 30 วัน | ลบ |

ผลคือประมาณ 78 ไฟล์แทน 720 โดยยังคงความละเอียดระดับชั่วโมงไว้สองวันล่าสุด
ซึ่งเป็นช่วงที่การกู้คืนจริงเกือบทั้งหมดย้อนไปถึง

```bash
cd backend
python scripts/prune_backups.py --backup-dir /path/to/backup/storage --dry-run
# ตรวจสอบผลลัพธ์ก่อน แล้วจึงรันจริงโดยไม่ใส่ --dry-run
python scripts/prune_backups.py --backup-dir /path/to/backup/storage
# ปรับหน้าต่างได้ถ้าจำเป็น
python scripts/prune_backups.py --backup-dir /path/to/backup/storage \
    --hourly-retention-hours 48 --daily-retention-days 30
```

- ลบเฉพาะไฟล์ที่ตรงรูปแบบชื่อ `mep-postgres-<environment>-<timestamp>.dump`
  ภายใน `--backup-dir` เท่านั้น — ไม่ใช่ `rm -rf` ทั่วไป
- **backup ล่าสุดจะไม่ถูกลบเด็ดขาด** แม้จะเก่าเกินทุกหน้าต่าง (เช่น ระบบตั้งเวลา
  หยุดทำงานไปนาน) เพื่อไม่ให้เหลือ backup เป็นศูนย์
- `.manifest.json` ของแต่ละ backup จะถูกลบไปพร้อมกัน
- `--retention-days` เดิมยังใช้ได้ และตอนนี้หมายถึงชั้นรายวัน ซึ่งเป็นความหมาย
  ที่มันตั้งใจไว้ตั้งแต่แรก
- `.\backup.ps1` เรียก prune ให้ทุกครั้งอยู่แล้ว การตั้งเวลา backup จึงได้ retention
  ไปด้วยโดยอัตโนมัติ

---

## 10. กรณีล้มเหลว (Failure handling)

| Scenario | Behavior |
|---|---|
| `pg_dump` fails | Non-zero exit, no manifest written, no partial `.dump` left behind, previous valid backups untouched. |
| Checksum mismatch at restore time | Hard fail — never proceeds to `pg_restore`. |
| `pg_restore` fails | Non-zero exit, error printed (no credentials), source database untouched. |
| Alembic revision mismatch after restore | Non-zero exit — restore is not considered verified. |
| Row-count mismatch (when `--source-database-url` given) | Non-zero exit. |
| Restore target looks like Production, or identical to source | Refused before any `pg_restore` invocation — see §5. |

---

## 11. ความปลอดภัย / การจัดการข้อมูล (Security / data handling)

- `DATABASE_URL` and the database password are never printed, logged, or
  placed on a subprocess command line (`ps`-visible) — passed via the
  `PGPASSWORD`/`PGHOST`/`PGUSER`/`PGPORT`/`PGDATABASE` subprocess
  environment instead (see `backend/scripts/pg_backup_lib.py`
  `ConnectionParams.as_libpq_env()`).
- Backup filenames and manifests never contain a username, password, or
  patient-adjacent identifier — only environment label, timestamp, baseline
  SHA, Alembic revision, file size, and checksum.
- Row-count verification reports counts only, never full row contents.
- Backup artifacts are never committed to Git (`/backups/` is
  `.gitignore`d at the repository root).


---

## 12. สำรองข้อมูลนอกเครื่องไป Google Drive (Off-host backup to Google Drive — PR25A)

### 12.1 What it does

Every `.\backup.ps1` run (the hourly task, or a manual run) first makes the
local verified backup exactly as before, **then** uploads the new archive and
its manifest to a folder (`MEP Database Backups`) in the department's Google
Drive.

- **A Drive failure never fails the backup and never deletes anything local.**
  The upload is recorded as pending and retried automatically by the next run
  (the pending queue is derived from what is on disk, so it cannot drift).
  Check `.\drive-backup.ps1 -Status`.
- **Same retention on Drive as local**, using the same selection function
  (`select_tiered_prune_candidates`): all backups for 48 hours, then the newest
  of each UTC day to 30 days; the newest backup is never deleted (section 9).
- The upload runs after the deployment lock is released, so a slow link cannot
  block an update.
- Scope requested: **`drive.file` only** — the tool can see only the files and
  folder it created itself, never the rest of the Drive.

### 12.2 One-time Google Cloud setup (department Gmail account)

A service account has no Drive quota on a consumer account, so the tool acts as
the account itself using OAuth consent, given once.

1. Sign in to <https://console.cloud.google.com/> as the department account and
   create a project (e.g. `mep-backup`). Enable the **Google Drive API**.
2. **Google Auth Platform / OAuth consent screen:** user type *External*, add
   the department account as a test user, scope `.../auth/drive.file`.
3. **Publish the app: set the publishing status to *In production*.** While in
   *Testing*, Google expires refresh tokens after **7 days**, which would break
   the backup every week. `drive.file` is a non-sensitive scope, so no Google
   verification is required; the consent screen will say the app is unverified
   (Advanced → continue) — expected for an internal tool.
4. **Clients → Create client → type "TVs and Limited Input devices".** Keep the
   *client ID* and *client secret* in the Owner's password manager: they are
   needed again on any recovery PC. (They are not enough to read the backups;
   consent as the department account is also required.)
5. Turn on 2-Step Verification for the department account, and do not share its
   password beyond the Owner.

### 12.3 One-time setup on the host

```powershell
cd deployment\local-staging
.\drive-backup.ps1 -Setup        # asks for client ID/secret, then prints a URL + code
```

Open the printed URL on any device, sign in as the department account, enter
the code and approve. The refresh token is saved to
`deployment\local-staging\secrets\drive-oauth.json` (gitignored; the directory
is restricted to the current user, SYSTEM and Administrators; the token is
never printed, logged, or put on a command line). Then:

```powershell
.\drive-backup.ps1 -Upload       # send the existing backups now
.\drive-backup.ps1 -Status       # confirm
.\drive-backup.ps1 -List         # what is on Drive
```

### 12.4 Scheduled task: hourly, no logged-in user

```powershell
.\schedule-backup.ps1 -Install   # prompts for the Windows account password
.\schedule-backup.ps1            # reports registration and last result
```

- Registered **with the account password**, as the Owner's other tools on this
  host are, so Task Scheduler runs it in a non-interactive session whether or
  not anyone is signed in. The password is handed straight to Task Scheduler;
  this repository never stores, logs or echoes it. Re-run `-Install` after a
  password change.
- Starts at **:15** past each hour (never :00 or :30, when the other tools on
  this host reach N Smart).
- S4U (no password) was *not* chosen: it gives a token without network
  credentials or cached secrets and cannot be shown from the repository to
  reach Docker Desktop's pipe and the user's Docker configuration.
- Still required: Docker Desktop running (set it to start with Windows and keep
  the account signed in / auto-logon), the PC awake (no sleep — PR25C
  checklist) and the account allowed to *log on as a batch job* (the default
  for local administrators).

### 12.5 Reading `-Status`

```
Drive backup:      CONFIGURED
Last local backup: mep-postgres-localstaging-...Z.dump (12 min ago)
Last upload:       mep-postgres-localstaging-...Z.dump (run finished ...)
Pending uploads:   0
STATUS: OK - Drive is up to date
```

Exit code 1 (and `STATUS: ATTENTION`) means pending uploads or a recorded
error. Common causes: network down (self-heals), `Re-run the setup command`
(token revoked/expired — repeat 12.3), Drive folder deleted (repeat 12.3).
A scheduled task that shows *success* can still have a stale Drive copy, so
check both `.\schedule-backup.ps1` and `.\drive-backup.ps1 -Status`.

### 12.6 Restore anywhere (fresh Docker-capable PC)

You need: the PC with Docker Desktop and PowerShell 7, this repository, the
OAuth client ID/secret (12.2 step 4), and the department Google account.

```powershell
cd deployment\local-staging
.\install.ps1                              # empty deployment on the new PC
.\drive-backup.ps1 -Setup                  # same client ID/secret; consent again
.\restore-from-drive.ps1 -ListOnly         # what is available
.\restore-from-drive.ps1 -KeepRehearsalDatabase            # latest
.\restore-from-drive.ps1 -Name mep-postgres-localstaging-<UTC>.dump -KeepRehearsalDatabase
```

`-Setup` on a new PC re-uses the existing Drive folder (found by name) — it
does not create a second one. The download is verified against its manifest
(SHA-256 and size) before it is accepted, then handed to the **existing**
restore path (`restore.ps1` → `restore_postgres.py`): checksum → identity →
production guard → same-source guard → empty-target guard → `pg_restore` →
Alembic check → row counts. No guard is bypassed. Like `restore.ps1`, it
restores into a *disposable verification database* and `-KeepRehearsalDatabase`
leaves it in place; it never overwrites the live database.

**Promoting the verified copy to live** (manual, Owner supervised; no
one-word command exists by design, see `restore.ps1`). Not exercised by any
automated test — rehearse it during UAT (PR24E) and time it for the RTO record
(section 7):

1. Note the kept database name printed by the restore
   (`mep_local_restore_rehearsal_<ts>`) and the live name (`POSTGRES_DB` in
   `.env`, default as installed).
2. `.\stop.ps1`, then start only PostgreSQL:
   `docker compose -p mep-local-staging -f compose.yml --env-file .env up -d --wait postgres`
3. Swap names (the application is stopped, so there are no live connections):
   `ALTER DATABASE <live> RENAME TO <live>_empty_before_restore;` then
   `ALTER DATABASE mep_local_restore_rehearsal_<ts> RENAME TO <live>;` using
   `docker compose ... exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "..."'`.
4. `.\start.ps1`, then `.\status.ps1` until Ready. If the installed
   application is newer than the backup's Alembic revision, run `.\update.ps1`
   (its pre-update backup gate and migration apply as usual).
5. Re-run `.\schedule-backup.ps1 -Install` on the new PC. Drop the
   `<live>_empty_before_restore` database once the Owner confirms.

Data written after the newest *uploaded* backup is lost (RPO). PR25D's client
journal is the planned mitigation for that gap.

### 12.7 What is and is not proven (as of PR25A)

| Claim | Evidence |
|---|---|
| Upload, queue/retry, idempotency, Drive retention, token never in logs/errors/state | `backend/tests/test_pr25a_drive_backup.py` (mocked HTTP) |
| Orchestration: mounts, no secret on a command line, Drive failure never fails a backup, restore binds to the downloaded file | `deployment/local-staging/tests/Invoke-InstallerTests.ps1` |
| Real Google consent (device flow), real upload, real Drive quota | **Not proven** — first run on the host |
| Scheduled task runs with no one logged in and reaches Docker | **Not proven** — verify on the host after `-Install` |
| Restore-anywhere on a fresh PC, and the promotion steps in 12.6 | **Not proven** — rehearse in UAT |

---

## Related documents

- `docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §11 (design
  authority), §24 (retention), §28 OD-PR24-3 (approved RPO/RTO/retention
  targets).
- `docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §17 (the evidence-slot template
  this runbook's §8 is built on), §1 (contact matrix / Database-backup
  contact role), §16 ("PR23 complete" vs. "ready for Production" distinction
  — the same distinction this document draws between "CI proves tooling"
  and "Staging rehearsal proves operational readiness").
- `docs/DECISION_LOG.md` — OD-PR24-3 resolution and PR24C's own entry.
