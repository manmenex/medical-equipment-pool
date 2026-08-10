import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { LegacyImportAccessGate } from "@/components/LegacyImportAccessGate";
import { LegacyImportFileDropzone } from "@/components/LegacyImportFileDropzone";
import { LegacyImportSkeletonBanner } from "@/components/LegacyImportSkeletonBanner";
import { useAuth } from "@/hooks/useAuth";
import { apiErrorMessage } from "@/services/api";
import { legacyImportClient } from "@/services/legacyImportClient";
import type { ImportCategory } from "@/types/legacyImport";
import { IMPORT_CATEGORY_LABELS } from "@/utils/legacyImportLabels";

// PR19B "Create import session flow": import type -> file selection ->
// "ตรวจสอบข้อมูล". Continuing never uploads the file or calls a real
// backend -- it only reads File.name/size/type locally (never the file's
// content) and asks the isolated LegacyImportClient for a canned preview
// session, then navigates to its read-only detail page. See
// services/legacyImportClient.ts / services/legacyImportFixtures.ts.
//
// Categories shown here (Equipment Master / Receive History / Issue
// History) are actually Roadmap PR20/PR21 scope, pulled forward into this
// PR19B skeleton per the Repository Owner's confirmed decision -- see
// types/legacyImport.ts's file-level note and the PR description.
const IMPORT_CATEGORIES: ImportCategory[] = ["equipment_master", "receive_history", "issue_history"];

type Step = "type" | "file";

export function LegacyImportCreatePage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [step, setStep] = useState<Step>("type");
  const [category, setCategory] = useState<ImportCategory | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
  }

  async function handleCreatePreview() {
    if (!category || !file) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await legacyImportClient.createPreviewSession({
        importCategory: category,
        file: { name: file.name, sizeBytes: file.size, type: file.type },
        requestedByDisplayName: user?.full_name ?? "ผู้ใช้งาน",
      });
      navigate(`/imports/${created.id}`);
    } catch (err) {
      setError(apiErrorMessage(err, "ไม่สามารถตรวจสอบข้อมูลได้ กรุณาลองใหม่"));
      setSubmitting(false);
    }
  }

  return (
    <LegacyImportAccessGate>
      <div className="flex max-w-xl flex-col gap-4">
        <LegacyImportSkeletonBanner />

        <div>
          <h1 className="text-lg font-semibold">เริ่มนำเข้าข้อมูลเดิม</h1>
          <p className="text-sm text-[var(--text-muted)]">
            ต้นแบบขั้นตอนเท่านั้น — ยังไม่มีการอัปโหลด ตรวจสอบ หรือนำเข้าข้อมูลจริงในขั้นตอนนี้
          </p>
        </div>

        <ol className="flex gap-2 text-xs font-medium text-[var(--text-muted)]" aria-label="ขั้นตอนการนำเข้าข้อมูล">
          <li className={step === "type" ? "text-status-borrowed" : ""}>1. เลือกประเภทข้อมูล</li>
          <li aria-hidden="true">›</li>
          <li className={step === "file" ? "text-status-borrowed" : ""}>2. เลือกไฟล์</li>
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
              ระบบจะแสดงเฉพาะชื่อไฟล์และขนาดไฟล์เท่านั้น ยังไม่มีการอ่านหรือตรวจสอบเนื้อหาไฟล์ในต้นแบบหน้าจอนี้
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
      </div>
    </LegacyImportAccessGate>
  );
}
