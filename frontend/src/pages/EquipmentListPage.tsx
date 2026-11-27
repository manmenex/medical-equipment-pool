import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { SourceBadge, SOURCE_FILTER_LABELS } from "@/components/SourceBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { useDebounce } from "@/hooks/useDebounce";
import { searchEquipment } from "@/services/equipment";
import { listCategories } from "@/services/masterData";
import type { EquipmentSource, EquipmentStatus } from "@/types";

const STATUS_OPTIONS: { value: EquipmentStatus | ""; label: string }[] = [
  { value: "", label: "ทุกสถานะ" },
  { value: "available_at_pool", label: "พร้อมใช้งาน" },
  { value: "issued_to_ward", label: "จ่ายให้ Ward แล้ว" },
  { value: "unavailable_defective", label: "ไม่พร้อมใช้งาน" },
  { value: "decommissioned", label: "ปลดระวางถาวร" },
];

const SOURCE_OPTIONS: { value: EquipmentSource | ""; label: string }[] = [
  { value: "", label: "ทุกประเภท" },
  { value: "pool", label: SOURCE_FILTER_LABELS.pool },
  { value: "demo", label: SOURCE_FILTER_LABELS.demo },
  { value: "loan", label: SOURCE_FILTER_LABELS.loan },
];

export function EquipmentListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(searchParams.get("q") ?? "");
  const status = (searchParams.get("status") as EquipmentStatus | null) ?? "";
  const source = (searchParams.get("source") as EquipmentSource | null) ?? "";
  const categoryId = searchParams.get("category_id") ?? "";
  const categories = useQuery({ queryKey: ["categories"], queryFn: listCategories, staleTime: 5 * 60_000 });
  const includeReturned = searchParams.get("include_returned") === "true";
  const debouncedQ = useDebounce(q, 150);

  const query = useInfiniteQuery({
    queryKey: ["equipment", "search", debouncedQ, status, source, categoryId, includeReturned],
    queryFn: ({ pageParam }) =>
      searchEquipment({
        q: debouncedQ || undefined,
        status: status || undefined,
        source: source || undefined,
        category_id: categoryId || undefined,
        include_returned: includeReturned || undefined,
        cursor: pageParam,
        limit: 30,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
  });

  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  const total = query.data?.pages[0]?.total ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold">ค้นหาเครื่องมือ</h1>
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
        <select
          aria-label="ประเภทเครื่อง"
          value={source}
          onChange={(e) => {
            const next = new URLSearchParams(searchParams);
            if (e.target.value) next.set("source", e.target.value);
            else next.delete("source");
            setSearchParams(next);
          }}
          className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
        >
          {SOURCE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <select
          aria-label="ชนิดเครื่อง"
          value={categoryId}
          onChange={(e) => {
            const next = new URLSearchParams(searchParams);
            if (e.target.value) next.set("category_id", e.target.value);
            else next.delete("category_id");
            setSearchParams(next);
          }}
          className="rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
        >
          <option value="">ทุกชนิด</option>
          {(categories.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={includeReturned}
            onChange={(e) => {
              const next = new URLSearchParams(searchParams);
              if (e.target.checked) next.set("include_returned", "true");
              else next.delete("include_returned");
              setSearchParams(next);
            }}
          />
          แสดงที่คืนผู้ให้ยืมแล้ว
        </label>
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
              <div className="flex items-center gap-2 truncate font-medium">
                {eq.equipment_name}
                <SourceBadge source={eq.equipment_source} />
              </div>
              <div className="truncate text-sm text-[var(--text-muted)]">
                {eq.equipment_source && eq.equipment_source !== "pool" ? `SN ${eq.bcm_code ?? "-"}` : (eq.asset_number ?? "-")}
                {eq.serial_number ? ` · SN ${eq.serial_number}` : ""}
                {eq.returned_to_owner_at ? " · คืนผู้ให้ยืมแล้ว" : ""}
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
