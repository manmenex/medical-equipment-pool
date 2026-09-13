import type { PrintValue, PrintValueType, ReportIdentity } from "@/types";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §9): "Receive and
// Issue default to landscape because of their wider transaction columns;
// Equipment Verify Checklist defaults to portrait" -- the approved,
// per-report-identity paper orientation. Not implementation-time layout
// evidence for switching Equipment Verify Checklist to landscape has been
// gathered, so it keeps the design's stated default.
export const PRINT_ORIENTATION: Record<ReportIdentity, "landscape" | "portrait"> = {
  "receive-report": "landscape",
  "issue-report": "landscape",
  "equipment-verify-checklist": "portrait",
};

const KNOWN_REPORT_IDENTITIES: ReportIdentity[] = ["receive-report", "issue-report", "equipment-verify-checklist"];

export function isReportIdentity(value: string | undefined): value is ReportIdentity {
  return !!value && (KNOWN_REPORT_IDENTITIES as string[]).includes(value);
}

const EMPTY_CELL = "-";

// Roadmap PR18C (design §7.2/§17): values arrive already backend-resolved
// and semantically typed -- this only renders them for paper, it never
// recomputes or reinterprets them. Dates/business dates render exactly as
// the backend's ISO "YYYY-MM-DD" string (the same convention
// ReportResultsTable.tsx already uses on-screen) rather than introducing an
// unapproved calendar conversion (e.g. Buddhist era) this repository has
// never established elsewhere.
export function formatPrintValue(value: PrintValue, valueType: PrintValueType): string {
  if (value === null || value === undefined) {
    return EMPTY_CELL;
  }
  if (valueType === "boolean") {
    return value ? "ใช่" : "ไม่ใช่";
  }
  if (valueType === "datetime" && typeof value === "string") {
    return formatDateTimeUtc(value);
  }
  return String(value);
}

// Roadmap PR18C: `generated_at` is the one datetime value this slice
// renders (no report column currently uses `value_type: "datetime"`).
// Formatted in the document's own `metadata.timezone` using the native
// `Intl` API -- no new dependency, no Buddhist-calendar conversion. `en-CA`
// is used only for its ISO-ordered (YYYY-MM-DD) numeric output, not for any
// locale-specific wording.
export function formatDateTimeInTimezone(iso: string, timezone: string): string {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(new Date(iso));
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
    return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
  } catch {
    return iso;
  }
}

function formatDateTimeUtc(iso: string): string {
  return formatDateTimeInTimezone(iso, "UTC");
}
