import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { canImportInventory, useAuth } from "@/hooks/useAuth";
import { apiErrorMessage } from "@/services/api";
import { createEquipment } from "@/services/equipment";
import { commitImport, previewImport } from "@/services/import";
import { listCategories, listDepartments, listLocations, listWards } from "@/services/masterData";
import type { ImportCommitResponse, ImportPreviewResponse, ImportRowResult, ImportRowStatus } from "@/types";

type Tab = "equipment" | "departments" | "wards" | "locations" | "categories" | "import";

const BASE_TABS: { key: Tab; label: string }[] = [
  { key: "equipment", label: "เพิ่มเครื่องมือ" },
  { key: "departments", label: "แผนก" },
  { key: "wards", label: "หอผู้ป่วย" },
  { key: "locations", label: "สถานที่" },
  { key: "categories", label: "หมวดหมู่" },
];

// Roadmap PR12 (Inventory Import): visible only to a user the frontend
// capability layer says can import -- purely a usability nicety (don't
// offer a tab that will 403), the backend remains the sole authority
// (see hooks/useAuth.ts's canImportInventory).
const IMPORT_TAB: { key: Tab; label: string } = { key: "import", label: "นำเข้าคลังเครื่องมือ" };

export function AdminPage() {
  const [tab, setTab] = useState<Tab>("equipment");
  const { user } = useAuth();
  const tabs = canImportInventory(user) ? [...BASE_TABS, IMPORT_TAB] : BASE_TABS;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold">จัดการระบบ</h1>
      <div className="flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
              tab === t.key ? "bg-status-borrowed text-white" : "surface border"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "equipment" && <EquipmentForm />}
      {tab === "departments" && <DepartmentsList />}
      {tab === "wards" && <WardsList />}
      {tab === "locations" && <LocationsList />}
      {tab === "categories" && <CategoriesList />}
      {tab === "import" && <InventoryImportPanel />}
    </div>
  );
}

function EquipmentForm() {
  const [assetNumber, setAssetNumber] = useState("");
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [bcmCode, setBcmCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    try {
      await createEquipment({
        asset_number: assetNumber,
        equipment_name: name,
        brand,
        model,
        bcm_code: bcmCode || undefined,
      });
      setMessage(`เพิ่มเครื่อง ${assetNumber} สำเร็จ`);
      setAssetNumber("");
      setName("");
      setBrand("");
      setModel("");
      setBcmCode("");
      queryClient.invalidateQueries({ queryKey: ["equipment"] });
    } catch (err) {
      setError(apiErrorMessage(err, "เพิ่มเครื่องมือไม่สำเร็จ"));
    }
  };

  return (
    <form onSubmit={handleSubmit} className="surface flex max-w-md flex-col gap-3 rounded-xl border p-4">
      <input
        required
        placeholder="เลขครุภัณฑ์ (Asset Number)"
        value={assetNumber}
        onChange={(e) => setAssetNumber(e.target.value)}
        className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
      />
      <input
        required
        placeholder="ชื่อเครื่องมือ"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
      />
      <input
        placeholder="ยี่ห้อ"
        value={brand}
        onChange={(e) => setBrand(e.target.value)}
        className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
      />
      <input
        placeholder="รุ่น"
        value={model}
        onChange={(e) => setModel(e.target.value)}
        className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
      />
      <input
        placeholder="รหัส BCM (ถ้ามี)"
        value={bcmCode}
        onChange={(e) => setBcmCode(e.target.value)}
        className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
      />
      {message && <p className="text-sm text-status-available">{message}</p>}
      {error && <p className="text-sm text-status-repair">{error}</p>}
      <button type="submit" className="rounded-lg bg-status-borrowed py-2.5 font-medium text-white">
        บันทึก
      </button>
    </form>
  );
}

function DepartmentsList() {
  const { data } = useQuery({ queryKey: ["departments"], queryFn: listDepartments });
  return (
    <ul className="surface divide-y rounded-xl border">
      {(data ?? []).map((d) => (
        <li key={d.id} className="px-4 py-2 text-sm">
          <span className="font-medium">{d.code}</span> — {d.name}
        </li>
      ))}
    </ul>
  );
}

function WardsList() {
  const { data } = useQuery({ queryKey: ["wards"], queryFn: listWards });
  return (
    <ul className="surface divide-y rounded-xl border">
      {(data ?? []).map((w) => (
        <li key={w.id} className="px-4 py-2 text-sm">
          <span className="font-medium">{w.code}</span> — {w.name}
        </li>
      ))}
    </ul>
  );
}

function LocationsList() {
  const { data } = useQuery({ queryKey: ["locations"], queryFn: listLocations });
  return (
    <ul className="surface divide-y rounded-xl border">
      {(data ?? []).map((l) => (
        <li key={l.id} className="px-4 py-2 text-sm">
          {l.name} {l.type ? `(${l.type})` : ""}
        </li>
      ))}
    </ul>
  );
}

function CategoriesList() {
  const { data } = useQuery({ queryKey: ["categories"], queryFn: listCategories });
  return (
    <ul className="surface divide-y rounded-xl border">
      {(data ?? []).map((c) => (
        <li key={c.id} className="px-4 py-2 text-sm">
          {c.name} — PM ทุก {c.default_pm_interval_days ?? "-"} วัน / CAL ทุก {c.default_cal_interval_days ?? "-"} วัน
        </li>
      ))}
    </ul>
  );
}

// Roadmap PR12 (Inventory Import, docs/audits/04-consolidated-implementation-plan.md
// Part D/F): upload -> preview -> commit, mirroring BorrowPage.tsx/
// ReturnPage.tsx's linear conditional-render stage pattern (guarded by
// state, not a numeric step index). Preview and commit are both
// independent uploads of the same raw file -- this component never sends
// a preview result back to the server as if it were the commit payload
// (see services/import.ts).
//
// Review finding PR12-H1R / Repository Owner decision: Roadmap PR12 is
// update-only -- it updates equipment that already exists in the system,
// matched by BCM Code. There is no control here to request anything else
// (see services/import.ts, which always sends update_existing=true).
function InventoryImportPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [previewResult, setPreviewResult] = useState<ImportPreviewResponse | null>(null);
  const [commitResult, setCommitResult] = useState<ImportCommitResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const reset = () => {
    setFile(null);
    setPreviewResult(null);
    setCommitResult(null);
    setError(null);
  };

  const handlePreview = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      setPreviewResult(await previewImport(file));
    } catch (err) {
      setError(apiErrorMessage(err, "ไม่สามารถอ่านไฟล์ได้"));
    } finally {
      setLoading(false);
    }
  };

  const handleCommit = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const result = await commitImport(file);
      setCommitResult(result);
      queryClient.invalidateQueries({ queryKey: ["equipment"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    } catch (err) {
      setError(apiErrorMessage(err, "นำเข้าข้อมูลไม่สำเร็จ"));
    } finally {
      setLoading(false);
    }
  };

  if (commitResult) {
    return (
      <div className="surface flex max-w-2xl flex-col gap-3 rounded-xl border p-4">
        <p className="text-sm font-medium text-status-available">นำเข้าข้อมูลสำเร็จ</p>
        <ImportSummary result={commitResult} />
        <ImportRowTable rows={commitResult.rows} />
        <button
          onClick={reset}
          className="w-fit rounded-lg bg-status-borrowed px-4 py-2.5 font-medium text-white"
        >
          นำเข้าไฟล์อื่น
        </button>
      </div>
    );
  }

  if (previewResult) {
    return (
      <div className="surface flex max-w-2xl flex-col gap-3 rounded-xl border p-4">
        <p className="text-sm font-medium">ตัวอย่างผลการนำเข้า (ยังไม่บันทึกข้อมูลลงระบบ)</p>
        <ImportSummary result={previewResult} />
        <ImportRowTable rows={previewResult.rows} />
        {error && <p className="text-sm text-status-repair">{error}</p>}
        <div className="flex gap-2">
          <button
            onClick={handleCommit}
            disabled={loading || previewResult.succeeded === 0}
            className="rounded-lg bg-status-borrowed px-4 py-2.5 font-medium text-white disabled:opacity-50"
          >
            {loading ? "กำลังบันทึก..." : "ยืนยันนำเข้า"}
          </button>
          <button onClick={reset} className="surface rounded-lg border px-4 py-2.5 font-medium">
            เลือกไฟล์ใหม่
          </button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handlePreview} className="surface flex max-w-md flex-col gap-3 rounded-xl border p-4">
      <input
        type="file"
        accept=".xlsx"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
      />
      <p className="text-sm text-[var(--text-muted)]">
        ระบบจะอัปเดตข้อมูลเฉพาะเครื่องมือที่มีอยู่แล้วในระบบ โดยจับคู่ด้วยรหัส BCM เท่านั้น
        หากไม่พบรหัส BCM ที่ตรงกัน แถวนั้นจะไม่ถูกบันทึกและจะไม่มีการสร้างรายการครุภัณฑ์ใหม่ —
        กรุณาสร้างรายการครุภัณฑ์ผ่านเมนู &quot;เพิ่มเครื่องมือ&quot; ก่อน แล้วจึงนำเข้าไฟล์นี้อีกครั้งเพื่ออัปเดต
      </p>
      {error && <p className="text-sm text-status-repair">{error}</p>}
      <button
        type="submit"
        disabled={!file || loading}
        className="rounded-lg bg-status-borrowed py-2.5 font-medium text-white disabled:opacity-50"
      >
        {loading ? "กำลังอ่านไฟล์..." : "ดูตัวอย่างก่อนนำเข้า"}
      </button>
    </form>
  );
}

function ImportSummary({ result }: { result: ImportPreviewResponse }) {
  return (
    <div className="flex flex-wrap gap-4 text-sm">
      <span>ทั้งหมด {result.total_rows}</span>
      <span className="text-status-available">สำเร็จ {result.succeeded}</span>
      <span className="text-status-repair">ล้มเหลว {result.failed}</span>
      <span className="text-status-borrowed">ข้าม {result.skipped}</span>
    </div>
  );
}

const ROW_STATUS_LABELS: Record<ImportRowStatus, string> = {
  success: "สำเร็จ",
  failed: "ล้มเหลว",
  skipped: "ข้าม",
};

function ImportRowTable({ rows }: { rows: ImportRowResult[] }) {
  return (
    <div className="max-h-80 overflow-y-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-[var(--border)]">
            <th className="py-1 pr-2">แถว</th>
            <th className="py-1 pr-2">BCM</th>
            <th className="py-1 pr-2">สถานะ</th>
            <th className="py-1 pr-2">หมายเหตุ</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.row_number} className="border-b border-[var(--border)] last:border-0">
              <td className="py-1 pr-2">{row.row_number}</td>
              <td className="py-1 pr-2">{row.bcm_code ?? "-"}</td>
              <td className="py-1 pr-2">{ROW_STATUS_LABELS[row.status]}</td>
              <td className="py-1 pr-2 text-[var(--text-muted)]">{row.reason ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
