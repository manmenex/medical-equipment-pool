# Backup / Restore Runbook — Medical Equipment Pool (Roadmap PR24C)
## คู่มือปฏิบัติการสำรองข้อมูลและกู้คืนข้อมูล — ระบบบริหารจัดการเครื่องมือแพทย์ส่วนกลาง

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
Once a managed PostgreSQL provider is selected, its own managed backup/PITR
capability may become the preferred RPO mechanism (§6 below) — this tooling
remains the provider-neutral fallback either way.

---

## 2. ก่อนเริ่ม (Prerequisites)

- `pg_dump` / `pg_restore` on `PATH`, matching (or compatible with) the
  target PostgreSQL server's major version.
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
stored. Provider-managed storage encryption satisfies this once a provider
is selected (OD-PR24-1); for interim manual/local rehearsal artifacts, use
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

`--source-database-url` is optional; when given, the script also diffs
representative-table row counts between source and restored databases.

**Restore target protection — no normal command path restores over
Production:**

- `--target-database-url` is **required**, with no default.
- `--target-environment` is **required** and refused outright if it equals
  `production` (case-insensitive) — there is no `--allow-production-restore`
  flag anywhere in this tooling, and none should be added.
- If `--source-database-url` is given, the target must be a physically
  different database (host+port+database name) than the source.
- The target database must be empty (no existing tables) unless
  `--force-non-empty-target` is passed — an extra guard beyond what a
  rehearsal normally needs to override.

**What the script verifies, in order:**

1. Backup checksum matches the manifest (hard fail on mismatch — never
   restores a corrupted/tampered artifact).
2. Restore-target guard (above).
3. `pg_restore` completes successfully.
4. The restored database's `alembic_version` matches the manifest's recorded
   revision — proving restore *fidelity*, before any question of running
   `alembic upgrade` (deliberately not run automatically; that is a separate,
   later step if the restored instance is ever used beyond verification).
5. Representative table row counts (`equipment`, `wards`, `users`,
   `borrow_transactions`, `audit_logs`) — diffed against the source if
   `--source-database-url` was given.

**On any verification failure:** the script exits non-zero and reports which
check failed. It never mutates the source database, and never silently
reports PASS.

---

## 6. หลักฐาน RPO (RPO evidence)

RPO ≤ 1 hour means the backup mechanism must be capable of producing a
recoverable backup at least hourly, or an equivalent provider-managed
continuous/PITR capability meeting the same target. Record, at the time of
each rehearsal or Production readiness review:

- Backup schedule/interval actually configured (e.g. "hourly, via cron
  invoking `backup_postgres.py`" or "provider-managed PITR, N-minute
  granularity").
- Timestamp of the most recent successful backup.
- Alerting/failure behavior if a scheduled backup does not complete
  successfully (a silent backup failure defeats the entire design — see
  `docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §21).

A single successful restore rehearsal does **not**, by itself, prove RPO —
RPO is a property of the *backup schedule's* reliability, not of one restore.

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

```bash
cd backend
python scripts/prune_backups.py --backup-dir /path/to/backup/storage --retention-days 30 --dry-run
# ตรวจสอบผลลัพธ์ก่อน แล้วจึงรันจริงโดยไม่ใส่ --dry-run
python scripts/prune_backups.py --backup-dir /path/to/backup/storage --retention-days 30
```

- ลบเฉพาะไฟล์ที่ตรงรูปแบบชื่อ `mep-postgres-<environment>-<timestamp>.dump`
  ภายใน `--backup-dir` เท่านั้น — ไม่ใช่ `rm -rf` ทั่วไป
- **backup ล่าสุดจะไม่ถูกลบเด็ดขาด** แม้จะเก่าเกิน retention (เช่น ระบบตั้งเวลา
  หยุดทำงานไปนาน) เพื่อไม่ให้เหลือ backup เป็นศูนย์
- `.manifest.json` ของแต่ละ backup จะถูกลบไปพร้อมกัน

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
