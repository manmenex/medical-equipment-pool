import { useEffect, useRef, useState } from "react";

import { useDebounce } from "@/hooks/useDebounce";
import { apiErrorMessage } from "@/services/api";
import { getOperatorOptions } from "@/services/reports";
import type { ReportOperatorOut } from "@/types";

interface OperatorAutocompleteProps {
  id?: string;
  label?: string;
  value: ReportOperatorOut | null;
  onChange: (operator: ReportOperatorOut | null) => void;
  placeholder?: string;
}

// Roadmap PR17 Slice 3 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §10.4/
// §12): the operator filter's selector. Calls only GET /report-options/
// operators (services/reports.ts's getOperatorOptions) -- never GET /users,
// and never exposes any user-management action. The selected operator's
// stable id (a UUID) is what the caller sends to the report endpoints;
// display_name is shown here only.
export function OperatorAutocomplete({
  id,
  label = "ผู้ปฏิบัติงาน",
  value,
  onChange,
  placeholder = "พิมพ์ชื่อผู้ปฏิบัติงาน",
}: OperatorAutocompleteProps) {
  const [query, setQuery] = useState(value?.display_name ?? "");
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ReportOperatorOut[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debouncedQuery = useDebounce(query, 250);
  const requestId = useRef(0);

  useEffect(() => {
    // A prior selection was cleared elsewhere (e.g. the filter form's
    // "ล้างตัวกรอง") -- keep the input text in sync without re-fetching.
    if (value === null && query !== "") return;
    if (value && query !== value.display_name) setQuery(value.display_name);
    // Only re-sync when the controlled `value` itself changes identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  useEffect(() => {
    const currentRequest = ++requestId.current;
    setIsLoading(true);
    setError(null);
    getOperatorOptions({ q: debouncedQuery || undefined, limit: 20 })
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
        setError(apiErrorMessage(err, "ไม่สามารถโหลดรายชื่อผู้ปฏิบัติงานได้"));
      });
  }, [debouncedQuery]);

  async function loadMore() {
    if (!nextCursor || isLoadingMore) return;
    setIsLoadingMore(true);
    try {
      const page = await getOperatorOptions({ q: debouncedQuery || undefined, limit: 20, cursor: nextCursor });
      // Cursor pages are appended exactly as returned -- never merged,
      // re-sorted, or de-duplicated client-side; the backend owns ordering.
      setOptions((prev) => [...prev, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (err) {
      setError(apiErrorMessage(err, "ไม่สามารถโหลดรายชื่อผู้ปฏิบัติงานได้"));
    } finally {
      setIsLoadingMore(false);
    }
  }

  function selectOperator(operator: ReportOperatorOut) {
    onChange(operator);
    setQuery(operator.display_name);
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
        <label htmlFor={id} className="mb-1 block text-xs text-[var(--text-muted)]">
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
          className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 pr-8 text-sm"
        />
        {value && (
          <button
            type="button"
            aria-label="ล้างผู้ปฏิบัติงานที่เลือก"
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
          {!isLoading && !error && options.length === 0 && (
            <p className="px-3 py-2 text-sm text-[var(--text-muted)]">ไม่พบผู้ปฏิบัติงาน</p>
          )}
          {!isLoading && !error && options.length > 0 && (
            <ul className="max-h-56 overflow-y-auto">
              {options.map((operator) => (
                <li key={operator.id}>
                  <button
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => selectOperator(operator)}
                    className="block w-full px-3 py-2 text-left text-sm hover:bg-status-borrowed/10"
                  >
                    {operator.display_name}
                    {!operator.is_active && (
                      <span className="ml-1 text-xs text-[var(--text-muted)]">(ไม่ใช้งานแล้ว)</span>
                    )}
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
