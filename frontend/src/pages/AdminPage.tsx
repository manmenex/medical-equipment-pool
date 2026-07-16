import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiErrorMessage } from "@/services/api";
import { createEquipment } from "@/services/equipment";
import { listCategories, listDepartments, listLocations, listWards } from "@/services/masterData";

type Tab = "equipment" | "departments" | "wards" | "locations" | "categories";

const TABS: { key: Tab; label: string }[] = [
  { key: "equipment", label: "เพิ่มเครื่องมือ" },
  { key: "departments", label: "แผนก" },
  { key: "wards", label: "หอผู้ป่วย" },
  { key: "locations", label: "สถานที่" },
  { key: "categories", label: "หมวดหมู่" },
];

export function AdminPage() {
  const [tab, setTab] = useState<Tab>("equipment");

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold">จัดการระบบ</h1>
      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
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
    </div>
  );
}

function EquipmentForm() {
  const [assetNumber, setAssetNumber] = useState("");
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    try {
      await createEquipment({ asset_number: assetNumber, equipment_name: name, brand, model });
      setMessage(`เพิ่มเครื่อง ${assetNumber} สำเร็จ`);
      setAssetNumber("");
      setName("");
      setBrand("");
      setModel("");
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
