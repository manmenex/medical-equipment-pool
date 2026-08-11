import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LegacyImportResultSummary } from "@/components/LegacyImportResultSummary";
import type { ImportResultSummary } from "@/types/legacyImport";

// PR19B result-summary rendering tests (review finding PR80-H2): the
// terminal-outcome card must reflect the session's real status, never
// force the green "นำเข้าสำเร็จ" card for a FAILED or CANCELLED session.
// Uses accessible text assertions, not color/class-only checks.

function makeResult(overrides: Partial<ImportResultSummary> = {}): ImportResultSummary {
  return {
    status: "completed",
    importedRows: 210,
    terminalAt: "2026-06-15T02:35:00Z",
    sessionId: "demo-1",
    ...overrides,
  };
}

describe("LegacyImportResultSummary", () => {
  it("completed: shows the success label and the numeric imported count", () => {
    render(<LegacyImportResultSummary result={makeResult({ status: "completed", importedRows: 210 })} />);

    expect(screen.getByText("นำเข้าสำเร็จ")).toBeInTheDocument();
    expect(screen.getByText("จำนวนแถวที่นำเข้าสำเร็จ")).toBeInTheDocument();
    expect(screen.getByText("210")).toBeInTheDocument();
    expect(screen.queryByText("การนำเข้าล้มเหลว")).not.toBeInTheDocument();
    expect(screen.queryByText("ยกเลิกการนำเข้า")).not.toBeInTheDocument();
  });

  it("completed with warnings: still shows successful-completion presentation, not a failure/cancel message", () => {
    render(<LegacyImportResultSummary result={makeResult({ status: "completed", importedRows: 205 })} />);

    expect(screen.getByText("นำเข้าสำเร็จ")).toBeInTheDocument();
    expect(screen.getByText("205")).toBeInTheDocument();
  });

  // PR80-H2 non-blocking cleanup: importedRows=0 is a real backend fact
  // (zero rows were imported) and must render as a literal "0", not be
  // confused with the unavailable (null) case below.
  it("completed with importedRows = 0: shows the real zero, not the unavailable message", () => {
    render(<LegacyImportResultSummary result={makeResult({ status: "completed", importedRows: 0 })} />);

    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.queryByText("ไม่ทราบจำนวนแถวที่นำเข้า")).not.toBeInTheDocument();
  });

  // null (no count available) must never be silently coerced to 0 -- that
  // would fabricate a specific numeric claim ("นำเข้า 0 แถว") the backend
  // never actually reported. This exercises the component defensively
  // even though this skeleton's own fixtures never produce a completed
  // session with a null importedRows (assertImportSessionInvariants
  // forbids it) -- the component itself must stay honest regardless.
  it("completed with importedRows = null: shows the unavailable message, never a fabricated 0", () => {
    render(<LegacyImportResultSummary result={makeResult({ status: "completed", importedRows: null })} />);

    expect(screen.getByText("ไม่ทราบจำนวนแถวที่นำเข้า")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("failed: never shows the success label, shows a failure message, and renders a null importedRows without crashing or claiming a count", () => {
    render(<LegacyImportResultSummary result={makeResult({ status: "failed", importedRows: null })} />);

    expect(screen.queryByText("นำเข้าสำเร็จ")).not.toBeInTheDocument();
    expect(screen.getByText("การนำเข้าล้มเหลว")).toBeInTheDocument();
    expect(screen.getByText(/ไม่มีข้อมูลถูกบันทึกลงระบบ/)).toBeInTheDocument();
  });

  it("cancelled: never shows the success label, shows a cancellation message, and renders a null importedRows without claiming a count", () => {
    render(<LegacyImportResultSummary result={makeResult({ status: "cancelled", importedRows: null })} />);

    expect(screen.queryByText("นำเข้าสำเร็จ")).not.toBeInTheDocument();
    expect(screen.getByText("ยกเลิกการนำเข้า")).toBeInTheDocument();
    expect(screen.getByText(/ไม่มีข้อมูลถูกนำเข้า/)).toBeInTheDocument();
  });

  it("cancelled: renders the terminal timestamp (backend always sets terminal_at for CANCELLED)", () => {
    render(
      <LegacyImportResultSummary
        result={makeResult({ status: "cancelled", importedRows: null, terminalAt: "2026-03-01T06:05:00Z" })}
      />
    );

    expect(screen.getByText("เวลาสิ้นสุด")).toBeInTheDocument();
    expect(screen.queryByText("-")).not.toBeInTheDocument();
  });

  it("no terminal status ever renders more than one of the three outcome presentations at once", () => {
    for (const status of ["completed", "failed", "cancelled"] as const) {
      const { unmount } = render(
        <LegacyImportResultSummary
          result={makeResult({ status, importedRows: status === "completed" ? 10 : null })}
        />
      );
      const successNode = screen.queryByText("นำเข้าสำเร็จ");
      const failureNode = screen.queryByText("การนำเข้าล้มเหลว");
      const cancelNode = screen.queryByText("ยกเลิกการนำเข้า");
      const presentCount = [successNode, failureNode, cancelNode].filter(Boolean).length;
      expect(presentCount).toBe(1);
      unmount();
    }
  });
});
