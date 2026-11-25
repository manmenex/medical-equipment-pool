import { useEffect, useMemo, useState } from "react";

import { ShiftChip } from "@/components/entry/ShiftChip";
import { useUiStore } from "@/store/uiStore";
import { resolveWardPhone } from "@/utils/wardPhone";
import type { Department, Ward } from "@/types";

interface WardSectionProps {
  title: string;
  contactLabel: string;
  wards: Ward[];
  departments: Department[];
  wardId: string;
  onWardChange: (id: string) => void;
  contact: string;
  onContact: (v: string) => void;
  phone: string;
  onPhone: (v: string) => void;
  /** Receipt may accept equipment from any ward, so the ward is optional there. */
  required?: boolean;
}

const inputCls = "w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm";

// Roadmap PR27/PR28 (D3/D7): section 1 of the ward-first screens -- type-ahead
// ward search, chips of the most used wards (local history only), the optional
// ward contact name and phone (prefilled from the ward, editable).
export function WardSection({
  title,
  contactLabel,
  wards,
  departments,
  wardId,
  onWardChange,
  contact,
  onContact,
  phone,
  onPhone,
}: WardSectionProps) {
  const wardUsage = useUiStore((s) => s.wardUsage);
  const lastWard = useUiStore((s) => s.lastWard);
  const selected = wards.find((w) => w.id === wardId);
  const [text, setText] = useState(selected?.name ?? "");
  const [open, setOpen] = useState(false);

  // Keep the text in step when the parent selects a ward (e.g. chips, restore).
  useEffect(() => {
    if (selected) setText(selected.name);
  }, [selected]);

  const matches = useMemo(() => {
    const t = text.trim().toLowerCase();
    if (!t || (selected && selected.name === text)) return [];
    return wards.filter((w) => w.name.toLowerCase().includes(t) || w.code.toLowerCase().includes(t)).slice(0, 8);
  }, [text, wards, selected]);

  const chips = useMemo(() => {
    const byUse = wards
      .filter((w) => (wardUsage[w.id] ?? 0) > 0)
      .sort((a, b) => (wardUsage[b.id] ?? 0) - (wardUsage[a.id] ?? 0));
    const list = byUse.slice(0, 4);
    if (list.length === 0 && lastWard) {
      const w = wards.find((x) => x.id === lastWard);
      if (w) list.push(w);
    }
    return list;
  }, [wards, wardUsage, lastWard]);

  const choose = (w: Ward) => {
    onWardChange(w.id);
    setText(w.name);
    setOpen(false);
    onPhone(resolveWardPhone(w, departments));
  };

  return (
    <section className="surface rounded-xl border p-3" aria-label={title}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        <ShiftChip />
      </div>
      <div className="relative">
        <input
          aria-label="ค้นหาหอผู้ป่วย"
          placeholder="พิมพ์ค้นหาหอผู้ป่วย"
          value={text}
          autoComplete="off"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            if (wardId) onWardChange("");
          }}
          className={inputCls}
        />
        {open && matches.length > 0 && (
          <ul role="listbox" className="surface absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-lg border shadow-lg">
            {matches.map((w) => (
              <li key={w.id} role="option" aria-selected={w.id === wardId}>
                <button
                  type="button"
                  onClick={() => choose(w)}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-status-borrowed/10"
                >
                  {w.name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {chips.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {chips.map((w) => (
            <button
              key={w.id}
              type="button"
              onClick={() => choose(w)}
              aria-pressed={w.id === wardId}
              className={`rounded-full border px-2.5 py-0.5 text-xs ${
                w.id === wardId ? "border-status-borrowed bg-status-borrowed/15 text-status-borrowed" : "border-[var(--border)]"
              }`}
            >
              {w.name}
            </button>
          ))}
        </div>
      )}
      <div className="mt-2 grid grid-cols-2 gap-2">
        <input
          aria-label={contactLabel}
          placeholder={contactLabel}
          value={contact}
          maxLength={100}
          onChange={(e) => onContact(e.target.value)}
          className={inputCls}
        />
        <input
          aria-label="เบอร์โทร"
          placeholder="เบอร์โทร"
          inputMode="tel"
          value={phone}
          maxLength={20}
          onChange={(e) => onPhone(e.target.value)}
          className={inputCls}
        />
      </div>
    </section>
  );
}
