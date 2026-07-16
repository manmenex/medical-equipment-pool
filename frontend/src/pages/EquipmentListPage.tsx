import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { StatusBadge } from "@/components/StatusBadge";
import { useDebounce } from "@/hooks/useDebounce";
import { searchEquipment } from "@/services/equipment";
import type { EquipmentStatus } from "@/types";

const STATUS_OPTIONS: { value: EquipmentStatus | ""; label: string }[] = [
  { value: "", label: "ทุกสถานะ" },
  { value: "available", label: "พร้อมใช้งาน" },
  { value: "borrowed", label: "ถูกยืม" },
  { value: "cleaning", label: "ทำความสะอาด" },
  { value: "pm", label: "PM" },
  { value: "calibration", label: "สอบเทียบ" },
  { value: "repair", label: "ซ่อม" },
  { value: "out_of_service", label: "ปลดระวาง" },
  { value: "lost", label: "สูญหาย" },
];

export function EquipmentListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const status = (searchParams.get("status") as EquipmentStatus | null) ?? "";
  const debouncedQ = useDebounce(q, 150);

  const query = useInfiniteQuery({
    queryKey: ["equipment", "search", debouncedQ, status],
    queryFn: ({ pageParam }) =>
      searchEquipment({ q: debouncedQ || undefined, status: status || undefined, cursor: pageParam, limit: 30 }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });

  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  const total = query.data?.pages[0]?.total ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 md:flex-row md:items-center">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="ค้นหา: ชื่อเครื่อง / เลขครุภัณฑ์ / Serial / QR"
          className="flex-1 rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 outline-none focus:border-status-borrowed"
        />
        <select
          value={status}
          onChange={(e) => {
            const next = new URLSearchParams(searchParams);
            if (e.target.value) next.set("status", e.target.value);
            else next.delete("status");
            setSearchParams(next);
          }}
          className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <div className="text-sm text-[var(--text-muted)]">พบ {total.toLocaleString()} รายการ</div>

      <div className="surface divide-y rounded-xl border">
        {items.map((eq) => (
          <Link
            key={eq.id}
            to={`/equipment/${eq.id}`}
            className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-black/5 dark:hover:bg-white/5"
          >
            <div className="min-w-0">
              <div className="truncate font-medium">{eq.equipment_name}</div>
              <div className="truncate text-sm text-[var(--text-muted)]">
                {eq.asset_number}
                {eq.serial_number ? ` · SN ${eq.serial_number}` : ""}
              </div>
            </div>
            <StatusBadge status={eq.status} />
          </Link>
        ))}
        {items.length === 0 && !query.isLoading && (
          <div className="px-4 py-8 text-center text-sm text-[var(--text-muted)]">ไม่พบเครื่องมือที่ค้นหา</div>
        )}
      </div>

      {query.hasNextPage && (
        <button
          onClick={() => query.fetchNextPage()}
          disabled={query.isFetchingNextPage}
          className="rounded-lg border border-[var(--border)] py-2 text-sm font-medium disabled:opacity-60"
        >
          {query.isFetchingNextPage ? "กำลังโหลด..." : "โหลดเพิ่มเติม"}
        </button>
      )}
    </div>
  );
}
