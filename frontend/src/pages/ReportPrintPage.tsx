import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";

import { PrintDocumentView } from "@/components/print/PrintDocumentView";
import { usePrintFontsReady } from "@/hooks/usePrintFontsReady";
import { apiErrorMessage } from "@/services/api";
import { buildPrintDataFilters, getReportPrintData } from "@/services/printReports";
import "@/styles/print.css";
import { isReportIdentity } from "@/utils/printFormat";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §9/§22 "PR18C --
// Browser print presentation"): a dedicated, bare print view -- deliberately
// NOT nested under AppShell (see App.tsx) so no navigation/dashboard chrome
// ever appears in the printed output. It fetches exactly one bounded
// PrintDocumentOut from the merged PR18B endpoint and renders it without
// filtering, sorting, or recomputing anything. The report page that links
// here (ReceiveReportPage/IssueReportPage/EquipmentVerifyChecklistPage)
// carries its own current URL filters over -- this page performs no
// business logic of its own; it forwards every filter present on the URL
// (review round 2, PR18C-H2R) and lets the backend's own
// `_reject_inapplicable_print_data_filters` decide what applies.
export function ReportPrintPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const [searchParams] = useSearchParams();

  const validReportId = isReportIdentity(reportId) ? reportId : null;

  // Roadmap PR18C review round 2 (PR18C-H2R): every filter present on the
  // URL is forwarded -- `getReportPrintData` itself strips `cursor`/`limit`
  // (see services/printReports.ts), and any other, report-inapplicable, or
  // unrecognized filter reaches the backend so its own validation -- not a
  // second frontend copy of it -- decides whether to accept or reject it.
  const filters = validReportId ? buildPrintDataFilters(searchParams) : {};

  const {
    data: printDocument,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["print-data", validReportId, filters],
    queryFn: () => getReportPrintData(validReportId!, filters),
    enabled: validReportId !== null,
  });

  // Roadmap PR18C review round 2 (PR18C-H1R): readiness is fail-closed and
  // tied to the specific `printDocument` currently on screen -- see
  // hooks/usePrintFontsReady.ts for the generation-token guard against a
  // stale, superseded document's font check overriding a newer one's status.
  const { status: fontsStatus, retry: retryFontsCheck } = usePrintFontsReady(printDocument);

  const isReady = !isLoading && !isError && !!printDocument && fontsStatus === "ready";

  function handlePrint() {
    // Defense-in-depth: the Print button is already disabled whenever
    // `!isReady`, but a rejected or stale font check must never be able to
    // trigger the browser's print dialog even if reached some other way.
    if (!isReady) {
      return;
    }
    window.print();
  }

  if (!validReportId) {
    return (
      <div className="p-6">
        <p className="text-sm text-red-600">ไม่รู้จักรายงานนี้ ไม่สามารถแสดงหน้าพิมพ์ได้</p>
      </div>
    );
  }

  return (
    <div>
      <div className="no-print sticky top-0 z-10 flex items-center justify-between border-b border-[#e2e8f0] bg-white p-3">
        <p className="text-sm text-[#64748b]">ตัวอย่างก่อนพิมพ์ -- โปรดตรวจสอบเนื้อหาก่อนพิมพ์จริง</p>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handlePrint}
            disabled={!isReady}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            พิมพ์
          </button>
          <button
            type="button"
            onClick={() => window.close()}
            className="rounded-lg border border-[#e2e8f0] px-4 py-2 text-sm font-medium"
          >
            ปิดหน้าต่างนี้
          </button>
        </div>
      </div>

      {isLoading && <p className="no-print p-6 text-sm text-[#64748b]">กำลังโหลดเอกสาร...</p>}

      {isError && (
        <div className="no-print flex flex-col items-start gap-2 p-6">
          <p className="text-sm text-red-600">{apiErrorMessage(error, "ไม่สามารถโหลดเอกสารสำหรับพิมพ์ได้")}</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm font-medium"
          >
            ลองใหม่
          </button>
        </div>
      )}

      {!isLoading && !isError && printDocument && fontsStatus === "error" && (
        <div className="no-print flex flex-col items-start gap-2 p-6">
          <p className="text-sm text-red-600">ไม่สามารถเตรียมฟอนต์สำหรับพิมพ์ได้ กรุณาลองใหม่ก่อนพิมพ์</p>
          <button
            type="button"
            onClick={retryFontsCheck}
            className="rounded-lg border border-[#e2e8f0] px-3 py-2 text-sm font-medium"
          >
            ลองใหม่
          </button>
        </div>
      )}

      {/* Roadmap PR18C review (fourth round, PR18C-H3): the browser cannot
          verify font availability at all -- no retry offered, since
          re-attempting cannot change what this browser supports. */}
      {!isLoading && !isError && printDocument && fontsStatus === "unsupported" && (
        <div className="no-print flex flex-col items-start gap-2 p-6">
          <p className="text-sm text-red-600">
            เบราว์เซอร์นี้ไม่รองรับการตรวจสอบฟอนต์สำหรับพิมพ์ จึงไม่สามารถแสดงตัวอย่างก่อนพิมพ์ได้อย่างปลอดภัย
          </p>
        </div>
      )}

      {!isLoading && !isError && printDocument && <PrintDocumentView document={printDocument} />}
    </div>
  );
}
