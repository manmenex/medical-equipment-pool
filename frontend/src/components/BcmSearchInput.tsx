import { useEffect, useRef, useState } from "react";

import { useDebounce } from "@/hooks/useDebounce";
import { searchBcmSuggestions } from "@/services/equipment";
import type { BcmSuggestion } from "@/types";

interface BcmSearchInputProps {
  onSelect: (suggestion: BcmSuggestion) => void;
  placeholder?: string;
}

// Roadmap PR5 fallback workflow: type BCM Code -> show matching/similar BCM
// Codes -> select one -> caller opens the matching equipment. The
// suggestion list shows BCM Code only (per the confirmed identifier
// rules) -- no device name, brand, model, serial number, or status.
export function BcmSearchInput({ onSelect, placeholder = "กรอกรหัส BCM" }: BcmSearchInputProps) {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<BcmSuggestion[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [open, setOpen] = useState(false);
  const debouncedQuery = useDebounce(query, 150);
  const requestId = useRef(0);

  useEffect(() => {
    const currentRequest = ++requestId.current;
    if (!debouncedQuery.trim()) {
      setSuggestions([]);
      setOpen(false);
      return;
    }
    searchBcmSuggestions(debouncedQuery)
      .then((results) => {
        // Ignore a stale response that resolved after a newer request.
        if (currentRequest !== requestId.current) return;
        setSuggestions(results);
        setActiveIndex(0);
        setOpen(results.length > 0);
      })
      .catch(() => {
        if (currentRequest !== requestId.current) return;
        setSuggestions([]);
        setOpen(false);
      });
  }, [debouncedQuery]);

  const selectSuggestion = (suggestion: BcmSuggestion) => {
    onSelect(suggestion);
    setQuery("");
    setSuggestions([]);
    setOpen(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      selectSuggestion(suggestions[activeIndex]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="relative">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        onFocus={() => suggestions.length > 0 && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 100)}
        placeholder={placeholder}
        autoComplete="off"
        className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2"
      />
      {open && (
        <ul className="surface absolute z-10 mt-1 w-full overflow-hidden rounded-lg border shadow-lg">
          {suggestions.map((s, i) => (
            <li key={s.id}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => selectSuggestion(s)}
                className={`block w-full px-3 py-2 text-left text-sm ${
                  i === activeIndex ? "bg-status-borrowed/10" : ""
                }`}
              >
                {s.bcm_code}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
