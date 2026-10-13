import { useEffect, useRef, useState } from "react";

import { useDebounce } from "@/hooks/useDebounce";
import { apiErrorMessage } from "@/services/api";
import { searchEquipment } from "@/services/equipment";
import type { Equipment } from "@/types";

interface EquipmentAutocompleteProps {
  id?: string;
  label?: string;
  value: Equipment | null;
  onChange: (equipment: Equipment | null) => void;
  placeholder?: string;
}

// Roadmap PR22F Fix Round 1 (§7-8 of the task): a bounded equipment lookup
// control, mirroring components/OperatorAutocomplete.tsx's established
// search-as-you-type + cursor "load more" pattern exactly, but backed by
// the existing services/equipment.ts searchEquipment (already used by
// EquipmentListPage) rather than a new endpoint. Lets hospital staff find
// equipment by name/asset number/BCM code instead of typing a raw UUID --
// only the resolved equipment.id is ever sent to the reconciliation
// findings filter.
export function EquipmentAutocomplete({
  id,
  label = "เครื่องมือ",
  value,
  onChange,
  placeholder = "พิมพ์ชื่อเครื่องมือ, เลขครุภัณฑ์ หรือรหัส BCM",
}: EquipmentAutocompleteProps) {
  const [query, setQuery] = useState(value?.equipment_name ?? "");
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<Equipment[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debouncedQuery = useDebounce(query, 250);
  const requestId = useRef(0);

  useEffect(() => {
    // A prior selection was cleared elsewhere (e.g. a filter reset) --
    // keep the input text in sync without re-fetching.
    if (value === null && query !== "") return;
    if (value && query !== value.equipment_name) setQuery(value.equipment_name);
    // Only re-sync when the controlled `value` itself changes identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  useEffect(() => {
    if (!debouncedQuery.trim()) {
      setOptions([]);
      setNextCursor(null);
      setIsLoading(false);
      setError(null);
      return;
    }
    const currentRequest = ++requestId.current;
    setIsLoading(true);
    setError(null);
    searchEquipment({ q: debouncedQuery, limit: 20 })
      .then((page) => {
        if (currentRequest !== requestId.current) return;
        setOptions(page.items);
        setNextCursor(page.next_cursor);
        setIsLoading(false);
      })
      .catch((err) => {
        if (currentRequest !== requestId.current) return;
        setOptions([]);
        setNextCursor(null);
        setIsLoading(false);
        setError(apiErrorMessage(err, "ไม่สามารถค้นหาเครื่องมือได้"));
      });
  }, [debouncedQuery]);

  async function loadMore() {
    if (!nextCursor || isLoadingMore) return;
    setIsLoadingMore(true);
    try {
      const page = await searchEquipment({ q: debouncedQuery, limit: 20, cursor: nextCursor });
      // Cursor pages are appended exactly as returned -- never merged,
      // re-sorted, or de-duplicated client-side; the backend owns ordering.
      setOptions((prev) => [...prev, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (err) {
      setError(apiErrorMessage(err, "ไม่สามารถค้นหาเครื่องมือได้"));
    } finally {
      setIsLoadingMore(false);
    }
  }

  function selectEquipment(equipment: Equipment) {
    onChange(equipment);
    setQuery(equipment.equipment_name);
    setOpen(false);
  }

  function clearSelection() {
    onChange(null);
    setQuery("");
    setOpen(false);
  }

  return (
    <div className="relative">
      {label && (
        <label htmlFor={id} className="mb-1 block text-xs font-medium text-[var(--text-muted)]">
          {label}
        </label>
      )}
      <div className="relative">
        <input
          id={id}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (value) onChange(null);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={placeholder}
          autoComplete="off"
          className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2.5 pr-8 text-sm"
        />
        {value && (
          <button
            type="button"
            aria-label="ล้างเครื่องมือที่เลือก"
            onMouseDown={(e) => e.preventDefault()}
            onClick={clearSelection}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
          >
            ×
          </button>
        )}
      </div>
      {open && (
        <div className="surface absolute z-10 mt-1 w-full overflow-hidden rounded-lg border shadow-lg">
          {isLoading && <p className="px-3 py-2 text-sm text-[var(--text-muted)]">กำลังค้นหา...</p>}
          {!isLoading && error && <p className="px-3 py-2 text-sm text-status-repair">{error}</p>}
          {!isLoading && !error && debouncedQuery.trim() !== "" && options.length === 0 && (
            <p className="px-3 py-2 text-sm text-[var(--text-muted)]">ไม่พบเครื่องมือ</p>
          )}
          {!isLoading && !error && options.length > 0 && (
            <ul className="max-h-56 overflow-y-auto">
              {options.map((equipment) => (
                <li key={equipment.id}>
                  <button
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => selectEquipment(equipment)}
                    className="block w-full px-3 py-2 text-left text-sm hover:bg-status-borrowed/10"
                  >
                    <div className="font-medium">{equipment.equipment_name}</div>
                    <div className="text-xs text-[var(--text-muted)]">
                      {equipment.asset_number}
                      {equipment.bcm_code ? ` · BCM ${equipment.bcm_code}` : ""}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {!isLoading && !error && nextCursor && (
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={loadMore}
              disabled={isLoadingMore}
              className="block w-full border-t border-[var(--border)] px-3 py-2 text-left text-sm font-medium disabled:opacity-60"
            >
              {isLoadingMore ? "กำลังโหลด..." : "โหลดเพิ่มเติม"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
