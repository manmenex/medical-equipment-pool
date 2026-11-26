import type { DemoLoanRowError, DemoLoanRowResult } from "@/services/equipment";

// Roadmap PR33 (D14): batch-registration helpers for demo/loan devices.

export interface BatchRow {
  /** Stable React key; never sent to the server. */
  key: number;
  serial: string;
  has_charger: boolean;
  has_clamp: boolean;
}

export const MAX_BATCH_ROWS = 200;

/**
 * Parse pasted text into serial numbers: one per line (a pasted Excel column
 * is newline-separated). For a pasted multi-column Excel range only the FIRST
 * cell of each line is used. Surrounding whitespace and wrapping double
 * quotes (Excel adds them to multi-line cells) are stripped; empty lines are
 * dropped. Order is kept and duplicates are NOT removed here -- the server
 * reports them per row so the operator sees exactly which rows clash.
 */
export function parseSerials(text: string): string[] {
  return text
    .split(/\r\n|\r|\n/)
    .map((line) => line.split("\t")[0].trim().replace(/^"(.*)"$/, "$1").trim())
    .filter((s) => s.length > 0);
}

let nextKey = 1;

/** Rows for newly pasted serials; accessories default to present (checked). */
export function makeRows(serials: string[]): BatchRow[] {
  return serials.map((serial) => ({ key: nextKey++, serial, has_charger: true, has_clamp: true }));
}

const ERROR_TEXT: Record<DemoLoanRowError, string> = {
  blank: "ว่าง",
  invalid_serial: "รูปแบบ Serial ไม่ถูกต้อง (ใช้ได้เฉพาะ A-Z 0-9 - _ . /)",
  duplicate_in_batch: "ซ้ำกับแถวอื่นในชุดนี้",
  duplicate_in_db: "มี Serial นี้ในระบบแล้ว",
};

export function rowErrorText(error: DemoLoanRowError): string {
  return ERROR_TEXT[error] ?? error;
}

/** Index -> row result, for the rows table. */
export function resultsByIndex(rows: DemoLoanRowResult[] | undefined): Map<number, DemoLoanRowResult> {
  return new Map((rows ?? []).map((r) => [r.index, r]));
}
