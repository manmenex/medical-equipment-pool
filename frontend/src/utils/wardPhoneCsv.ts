import type { WardPhoneImportRow } from "@/types";

export const MAX_PHONE_IMPORT_ROWS = 500;

export interface ParsedPhoneCsv {
  rows: WardPhoneImportRow[];
  error: string | null;
}

// Minimal RFC-4180-ish parser (quoted fields, "" escapes, CRLF/LF).
function parseCsv(text: string): string[][] {
  const out: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else quoted = false;
      } else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      out.push(row);
      row = [];
    } else field += c;
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    out.push(row);
  }
  return out.filter((r) => r.some((f) => f.trim() !== ""));
}

// Parses pasted/uploaded CSV with header ward_name,phone. Extra columns
// (e.g. nsmart_department) are ignored. A leading UTF-8 BOM is stripped.
export function parseWardPhoneCsv(input: string): ParsedPhoneCsv {
  const text = input.replace(/^﻿/, "");
  const table = parseCsv(text);
  if (table.length === 0) return { rows: [], error: "ไม่พบข้อมูล" };
  const header = table[0].map((h) => h.replace(/^﻿/, "").trim().toLowerCase());
  const nameIdx = header.indexOf("ward_name");
  const phoneIdx = header.indexOf("phone");
  if (nameIdx < 0 || phoneIdx < 0) {
    return { rows: [], error: "ต้องมีหัวคอลัมน์ ward_name และ phone" };
  }
  const rows = table.slice(1).map((r) => ({
    ward_name: (r[nameIdx] ?? "").trim(),
    phone: (r[phoneIdx] ?? "").trim(),
  }));
  if (rows.length === 0) return { rows: [], error: "ไม่พบแถวข้อมูล" };
  if (rows.length > MAX_PHONE_IMPORT_ROWS) {
    return { rows: [], error: `จำนวนแถวเกิน ${MAX_PHONE_IMPORT_ROWS} แถว (พบ ${rows.length})` };
  }
  return { rows, error: null };
}
