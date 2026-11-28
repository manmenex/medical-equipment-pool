import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { DemoLoanBatchPanel } from "@/components/DemoLoanBatchPanel";
import { PhoneEditRow } from "@/components/PhoneEditRow";
import { UsersPanel } from "@/components/UsersPanel";
import { WardPhoneImportPanel } from "@/components/WardPhoneImportPanel";
import {
  canImportInventory,
  canManageEquipmentMasterData,
  canManageUsers,
  canManageWardPhones,
  useAuth,
} from "@/hooks/useAuth";
import axios from "axios";

import { apiErrorMessage } from "@/services/api";
import { createEquipment } from "@/services/equipment";
import { commitImport, previewImport } from "@/services/import";
import { listCategories, listDepartments, listWards, createDepartment, createWard, updateDepartmentPhone, updateWardPhone } from "@/services/masterData";
import type { ImportCommitResponse, ImportPreviewResponse, ImportRowResult, ImportRowStatus } from "@/types";

type Tab = "equipment" | "demoLoan" | "departments" | "wards" | "categories" | "import" | "wardPhones" | "users";

const ALL_TAB_KEYS: Tab[] = ["equipment", "demoLoan", "departments", "wards", "categories", "import", "wardPhones", "users"];

const BASE_TABS: { key: Tab; label: string }[] = [
  { key: "equipment", label: "เพิ่มเครื่องมือ" },
  { key: "departments", label: "แผนก" },
  { key: "wards", label: "หอผู้ป่วย" },
  { key: "categories", label: "หมวดหมู่" },
];

// Roadmap PR12 (Inventory Import): visible only to a user the frontend
// capability layer says can import -- purely a usability nicety (don't
// offer a tab that will 403), the backend remains the sole authority
// (see hooks/useAuth.ts's canImportInventory).
const IMPORT_TAB: { key: Tab; label: string } = { key: "import", label: "นำเข้าคลังเครื่องมือ" };

const WARD_PHONES_TAB: { key: Tab; label: string } = { key: "wardPhones", label: "นำเข้าเบอร์โทรหอผู้ป่วย" };

const USERS_TAB: { key: Tab; label: string } = { key: "users", label: "ผู้ใช้" };

// Roadmap PR33 (D14): administrator-only demo/loan batch registration (usability gate only;
// the backend remains authoritative).
const DEMO_LOAN_TAB: { key: Tab; label: string } = { key: "demoLoan", label: "เพิ่มเครื่อง Demo/ยืม" };

export function AdminPage() {
  const [searchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab");
  // Deep link from the Settings hub (?tab=users etc.); unknown values fall back.
  const [selectedTab, setTab] = useState<Tab>(
    ALL_TAB_KEYS.includes(requestedTab as Tab) ? (requestedTab as Tab) : "equipment",
  );
  const { user } = useAuth();
  const tabs = [
    BASE_TABS[0],
    ...(canManageEquipmentMasterData(user) ? [DEMO_LOAN_TAB] : []),
    ...BASE_TABS.slice(1),
    ...(canImportInventory(user) ? [IMPORT_TAB] : []),
    ...(canManageWardPhones(user) ? [WARD_PHONES_TAB] : []),
    ...(canManageUsers(user) ? [USERS_TAB] : []),
  ];
  // A deep-linked tab the user may not see (e.g. ?tab=import) falls back.
  const tab: Tab = tabs.some((t) => t.key === selectedTab) ? selectedTab : "equipment";

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
      {tab === "demoLoan" && canManageEquipmentMasterData(user) && <DemoLoanBatchPanel />}
      {tab === "departments" && <DepartmentsList />}
      {tab === "wards" && <WardsList />}
      {tab === "categories" && <CategoriesList />}
      {tab === "import" && canImportInventory(user) && <InventoryImportPanel />}
      {tab === "users" && canManageUsers(user) && <UsersPanel currentUserId={user?.id} />}
      {tab === "wardPhones" && canManageWardPhones(user) && <WardPhoneImportPanel />}
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
        asset_number: assetNumber.trim() || undefined,
        equipment_name: name,
        brand,
        model,
        bcm_code: bcmCode || undefined,
      });
      setMessage(`เพิ่มเครื่อง ${assetNumber.trim() || name} สำเร็จ`);
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
        placeholder="เลขครุภัณฑ์ (ไม่บังคับ)"
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

function masterDataError(err: unknown, noun: string): string {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status;
    if (status === 409) return `รหัสหรือชื่อ${noun}นี้มีอยู่ในระบบแล้ว`;
    if (status === 422) return "ข้อมูลไม่ถูกต้อง กรุณาตรวจสอบรหัส ชื่อ และเบอร์โทร";
    if (status === 403) return `คุณไม่มีสิทธิ์เพิ่ม${noun}`;
  }
  return apiErrorMessage(err, `เพิ่ม${noun}ไม่สำเร็จ`);
}

const INPUT_CLASS = "rounded-lg border border-[var(--border)] bg-transparent px-3 py-2";

function AddMasterDataForm({
  noun,
  addLabel,
  showDepartment,
  onCreate,
}: {
  noun: string;
  addLabel: string;
  showDepartment: boolean;
  onCreate: (v: { code: string; name: string; phone: string | null; departmentId: string | null }) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { data: departments } = useQuery({ queryKey: ["departments"], queryFn: listDepartments, enabled: showDepartment && open });

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="self-start rounded-lg bg-status-borrowed px-4 py-2 text-sm font-medium text-white">
        {addLabel}
      </button>
    );
  }
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!code.trim() || !name.trim()) {
      setError("กรุณากรอกรหัสและชื่อ");
      return;
    }
    setBusy(true);
    try {
      await onCreate({ code: code.trim(), name: name.trim(), phone: phone.trim() || null, departmentId: departmentId || null });
      setCode("");
      setName("");
      setPhone("");
      setDepartmentId("");
      setOpen(false);
    } catch (err) {
      setError(masterDataError(err, noun));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="surface flex max-w-md flex-col gap-3 rounded-xl border p-4">
      <input aria-label={`รหัส${noun}`} placeholder={`รหัส${noun}`} value={code} onChange={(e) => setCode(e.target.value)} className={INPUT_CLASS} />
      <input aria-label={`ชื่อ${noun}`} placeholder={`ชื่อ${noun}`} value={name} onChange={(e) => setName(e.target.value)} className={INPUT_CLASS} />
      <input aria-label="เบอร์โทร" placeholder="เบอร์โทร (ไม่บังคับ)" value={phone} onChange={(e) => setPhone(e.target.value)} className={INPUT_CLASS} />
      {showDepartment && (
        <select aria-label="แผนก" value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} className={INPUT_CLASS}>
          <option value="">ไม่ระบุแผนก</option>
          {(departments ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.code} — {d.name}
            </option>
          ))}
        </select>
      )}
      {error && (
        <p role="alert" className="text-sm text-status-repair">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className="rounded-lg bg-status-borrowed px-4 py-2 text-sm font-medium text-white">
          บันทึก
        </button>
        <button type="button" onClick={() => setOpen(false)} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm">
          ยกเลิก
        </button>
      </div>
    </form>
  );
}

function DepartmentsList() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["departments"], queryFn: listDepartments });
  return (
    <div className="flex flex-col gap-3">
      {canManageEquipmentMasterData(user) && (
        <AddMasterDataForm
          noun="แผนก"
          addLabel="เพิ่มแผนก"
          showDepartment={false}
          onCreate={async (v) => {
            await createDepartment({ code: v.code, name: v.name, phone: v.phone });
            await queryClient.invalidateQueries({ queryKey: ["departments"] });
          }}
        />
      )}
      <ul className="surface divide-y rounded-xl border">
      {(data ?? []).map((d) => (
        <PhoneEditRow
          key={d.id}
          label={`${d.code} — ${d.name}`}
          phone={d.phone}
          canEdit={canManageWardPhones(user)}
          onSave={async (phone) => {
            await updateDepartmentPhone(d.id, phone);
            await queryClient.invalidateQueries({ queryKey: ["departments"] });
          }}
        />
      ))}
    </ul>
    </div>
  );
}

function WardsList() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["wards"], queryFn: listWards });
  return (
    <div className="flex flex-col gap-3">
      {canManageEquipmentMasterData(user) && (
        <AddMasterDataForm
          noun="หอผู้ป่วย"
          addLabel="เพิ่มหอผู้ป่วย"
          showDepartment
          onCreate={async (v) => {
            await createWard({ code: v.code, name: v.name, phone: v.phone, department_id: v.departmentId });
            await queryClient.invalidateQueries({ queryKey: ["wards"] });
          }}
        />
      )}
      <ul className="surface divide-y rounded-xl border">
      {(data ?? []).map((w) => (
        <PhoneEditRow
          key={w.id}
          label={`${w.code} — ${w.name}`}
          phone={w.phone}
          canEdit={canManageWardPhones(user)}
          onSave={async (phone) => {
            await updateWardPhone(w.id, phone);
            await queryClient.invalidateQueries({ queryKey: ["wards"] });
          }}
        />
      ))}
    </ul>
    </div>
  );
}

function CategoriesList() {
  const { data } = useQuery({ queryKey: ["categories"], queryFn: listCategories });
  return (
    <ul className="surface divide-y rounded-xl border">
      {(data ?? []).map((c) => (
        <li key={c.id} className="px-4 py-2 text-sm">
          {c.name}
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
        อัปเดตเฉพาะเครื่องที่มีอยู่แล้ว จับคู่ด้วย BCM แถวที่ไม่พบ BCM จะไม่ถูกบันทึก
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
