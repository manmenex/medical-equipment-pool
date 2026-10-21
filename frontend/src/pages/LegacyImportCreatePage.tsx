import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { LegacyImportAccessGate } from "@/components/LegacyImportAccessGate";
import { LegacyImportFileDropzone } from "@/components/LegacyImportFileDropzone";
import { createEquipmentMasterSession, uploadEquipmentMasterSource } from "@/services/equipmentMasterImportClient";
import {
  approveLegacyMigrationAuthority,
  findLegacyMigrationAuthorityByChecksum,
} from "@/services/legacyMigrationAuthorityClient";
import { createLegacyHistorySession, uploadLegacyHistorySource } from "@/services/legacyHistoryImportClient";
import type { ImportCategory } from "@/types/legacyImport";
import { IMPORT_CATEGORY_LABELS } from "@/utils/legacyImportLabels";
import { describeEquipmentMasterImportError, describeLegacyHistoryImportError } from "@/utils/legacyImportApiErrors";

// Roadmap PR20F/PR21E: import type -> file selection -> "ตรวจสอบข้อมูล".
// Both real categories create a real ImportSession and upload/register the
// file through the actual backend source-upload API -- the backend
// computes the checksum itself; this page never parses the workbook or
// inspects business fields locally, only File.name/size/type for the
// picker UI.
const IMPORT_CATEGORIES: ImportCategory[] = ["equipment_master", "legacy_transaction_history"];

type Step = "type" | "file" | "authority";

export function LegacyImportCreatePage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("type");
  const [category, setCategory] = useState<ImportCategory | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Roadmap PR20F/PR21E: if the session was created but the source upload
  // then failed (e.g. a network error), retrying re-uses this same session
  // instead of creating a second, sourceless ImportSession for one user
  // action.
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);

  // Roadmap PR21E (design §6-§11): the migration-authority checksum comes
  // only from a real ImportSourceOut response (never hand-typed) -- held
  // here only for the duration of this create flow, since there is no
  // endpoint to re-fetch an existing session's source checksum later. If
  // the operator abandons this page after upload but before approving, the
  // session still exists (created, sourced) but its checksum cannot be
  // recovered here again; a fresh import session must be started. The
  // ordinary validate/dry-run/confirm/execute workflow on the detail page
  // never needs this value again once approval succeeds.
  const [pendingChecksum, setPendingChecksum] = useState<string | null>(null);
  const [checkingAuthority, setCheckingAuthority] = useState(false);
  const [approving, setApproving] = useState(false);
  const [authorityDialogOpen, setAuthorityDialogOpen] = useState(false);
  const [authorityError, setAuthorityError] = useState<string | null>(null);

  const canContinueFromType = category !== null;
  const canContinueFromFile = file !== null && !submitting;

  // Changing the import category invalidates any file already selected
  // for the previous category -- a file picked for one dataset type must
  // never silently carry over to a different one. Also clears any
  // file-dependent error/submission state so the "ตรวจสอบข้อมูล" step
  // always starts clean for the newly selected category.
  function handleSelectCategory(next: ImportCategory) {
    setCategory(next);
    setFile(null);
    setError(null);
    setPendingSessionId(null);
    setPendingChecksum(null);
    setAuthorityError(null);
  }

  async function checkAuthorityThenNavigate(sessionId: string, checksum: string) {
    setCheckingAuthority(true);
    setAuthorityError(null);
    try {
      const authority = await findLegacyMigrationAuthorityByChecksum(checksum);
      if (authority) {
        navigate(`/imports/${sessionId}`);
        return;
      }
      // Not yet approved -- show the explicit, Administrator-only approval
      // step below. Never auto-approved.
      setStep("authority");
    } catch (err) {
      setAuthorityError(describeLegacyHistoryImportError(err).message);
      setStep("authority");
    } finally {
      setCheckingAuthority(false);
    }
  }

  async function handleCreatePreview() {
    if (!category || !file) return;
    setSubmitting(true);
    setError(null);

    if (category === "equipment_master") {
      try {
        const sessionId = pendingSessionId ?? (await createEquipmentMasterSession()).id;
        setPendingSessionId(sessionId);
        await uploadEquipmentMasterSource(sessionId, file);
        navigate(`/imports/${sessionId}`);
      } catch (err) {
        setError(describeEquipmentMasterImportError(err).message);
        setSubmitting(false);
      }
      return;
    }

    try {
      const sessionId = pendingSessionId ?? (await createLegacyHistorySession()).id;
      setPendingSessionId(sessionId);
      const source = await uploadLegacyHistorySource(sessionId, file);
      setPendingChecksum(source.checksum);
      setSubmitting(false);
      await checkAuthorityThenNavigate(sessionId, source.checksum);
    } catch (err) {
      setError(describeLegacyHistoryImportError(err).message);
      setSubmitting(false);
    }
  }

  async function handleApproveAuthority() {
    if (!pendingChecksum || !pendingSessionId) return;
    setApproving(true);
    setAuthorityError(null);
    try {
      await approveLegacyMigrationAuthority(pendingChecksum);
      navigate(`/imports/${pendingSessionId}`);
    } catch (err) {
      setAuthorityError(describeLegacyHistoryImportError(err).message);
    } finally {
      setApproving(false);
    }
  }

  return (
    <LegacyImportAccessGate>
      <div className="flex max-w-xl flex-col gap-4">
        <div>
          <h1 className="text-lg font-semibold">เริ่มนำเข้าข้อมูลเดิม</h1>
          <p className="text-sm text-[var(--text-muted)]">
            ไฟล์ที่เลือกจะถูกอัปโหลดไปยังระบบจริงเมื่อกด &quot;ตรวจสอบข้อมูล&quot;
          </p>
        </div>

        <ol className="flex gap-2 text-xs font-medium text-[var(--text-muted)]" aria-label="ขั้นตอนการนำเข้าข้อมูล">
          <li className={step === "type" ? "text-status-borrowed" : ""}>1. เลือกประเภทข้อมูล</li>
          <li aria-hidden="true">›</li>
          <li className={step === "file" ? "text-status-borrowed" : ""}>2. เลือกไฟล์</li>
          {category === "legacy_transaction_history" && (
            <>
              <li aria-hidden="true">›</li>
              <li className={step === "authority" ? "text-status-borrowed" : ""}>3. อนุมัติไฟล์</li>
            </>
          )}
        </ol>

        {step === "type" && (
          <div className="surface flex flex-col gap-3 rounded-xl border p-4">
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-sm font-medium">ประเภทข้อมูลที่ต้องการนำเข้า *</legend>
              {IMPORT_CATEGORIES.map((c) => (
                <label
                  key={c}
                  className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-sm ${
                    category === c ? "border-status-borrowed bg-status-borrowed/5" : "border-[var(--border)]"
                  }`}
                >
                  <input
                    type="radio"
                    name="import-category"
                    value={c}
                    checked={category === c}
                    onChange={() => handleSelectCategory(c)}
                  />
                  {IMPORT_CATEGORY_LABELS[c]}
                </label>
              ))}
            </fieldset>
            <button
              type="button"
              disabled={!canContinueFromType}
              onClick={() => setStep("file")}
              className="w-fit rounded-lg bg-status-borrowed px-4 py-2.5 font-medium text-white disabled:opacity-50"
            >
              ถัดไป
            </button>
          </div>
        )}

        {step === "file" && (
          <div className="surface flex flex-col gap-3 rounded-xl border p-4">
            <LegacyImportFileDropzone file={file} onSelect={setFile} onRemove={() => setFile(null)} />
            <p className="text-sm text-[var(--text-muted)]">
              ระบบจะตรวจสอบไฟล์นี้หลังอัปโหลด ยังไม่มีการอ่านหรือตรวจสอบเนื้อหาไฟล์ในเครื่องของคุณ
            </p>
            {error && (
              <p role="alert" className="text-sm text-status-repair">
                {error}
              </p>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setStep("type")}
                disabled={submitting}
                className="rounded-lg border border-[var(--border)] px-4 py-2.5 font-medium disabled:opacity-60"
              >
                ย้อนกลับ
              </button>
              <button
                type="button"
                disabled={!canContinueFromFile}
                onClick={handleCreatePreview}
                className="rounded-lg bg-status-borrowed px-4 py-2.5 font-medium text-white disabled:opacity-50"
              >
                {submitting ? "กำลังตรวจสอบข้อมูล..." : "ตรวจสอบข้อมูล"}
              </button>
            </div>
          </div>
        )}

        {step === "authority" && (
          <div className="surface flex flex-col gap-3 rounded-xl border p-4">
            <h2 className="text-sm font-semibold">อนุมัติไฟล์สำหรับนำเข้าประวัติการรับ-ส่งเครื่องมือเดิม</h2>
            {checkingAuthority ? (
              <p className="text-sm text-[var(--text-muted)]">กำลังตรวจสอบสถานะการอนุมัติไฟล์...</p>
            ) : (
              <>
                <p className="text-sm text-[var(--text-muted)]">
                  ไฟล์นี้ยังไม่ได้รับการอนุมัติให้ใช้นำเข้าข้อมูลชุดนี้ ต้องมีผู้ดูแลระบบอนุมัติไฟล์นี้ก่อนจึงจะทดลองนำเข้าข้อมูลได้
                  การอนุมัตินี้ผูกกับเนื้อหาไฟล์ที่อัปโหลดจริงเท่านั้น (ตรวจสอบจาก checksum ที่ระบบคำนวณเอง)
                </p>
                {authorityError && (
                  <p role="alert" className="text-sm text-status-repair">
                    {authorityError}
                  </p>
                )}
                <div>
                  <button
                    type="button"
                    onClick={() => setAuthorityDialogOpen(true)}
                    disabled={approving}
                    className="w-fit rounded-lg bg-status-borrowed px-4 py-2.5 font-medium text-white disabled:opacity-50"
                  >
                    {approving ? "กำลังอนุมัติ..." : "อนุมัติไฟล์นี้"}
                  </button>
                </div>
              </>
            )}

            {authorityDialogOpen && (
              <div
                role="alertdialog"
                aria-modal="true"
                aria-labelledby="approve-authority-dialog-title"
                aria-describedby="approve-authority-dialog-body"
                className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
              >
                <div className="surface w-full max-w-md rounded-xl border p-4">
                  <h4 id="approve-authority-dialog-title" className="text-base font-semibold">
                    ยืนยันการอนุมัติไฟล์
                  </h4>
                  <p id="approve-authority-dialog-body" className="mt-2 text-sm text-[var(--text-muted)]">
                    การอนุมัตินี้จะอนุญาตให้ไฟล์ที่อัปโหลดไว้ (ตามเนื้อหาไฟล์จริง) ถูกใช้ทดลองนำเข้าประวัติการรับ-ส่งเครื่องมือเดิมได้
                    ยังไม่มีการบันทึกข้อมูลลงระบบจากขั้นตอนนี้
                  </p>
                  <div className="mt-4 flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => setAuthorityDialogOpen(false)}
                      className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
                    >
                      ยกเลิก
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setAuthorityDialogOpen(false);
                        handleApproveAuthority();
                      }}
                      className="rounded-lg bg-status-borrowed px-3 py-2 text-sm font-medium text-white"
                    >
                      อนุมัติ
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </LegacyImportAccessGate>
  );
}
