import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { PrintDocumentView } from "@/components/print/PrintDocumentView";
import { apiErrorMessage } from "@/services/api";
import { getReportPrintData } from "@/services/printReports";
import "@/styles/print.css";
import { isReportIdentity } from "@/utils/printFormat";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §9/§22 "PR18C --
// Browser print presentation"): a dedicated, bare print view -- deliberately
// NOT nested under AppShell (see App.tsx) so no navigation/dashboard chrome
// ever appears in the printed output. It fetches exactly one bounded
// PrintDocumentOut from the merged PR18B endpoint and renders it without
// filtering, sorting, or recomputing anything. The report page that links
// here (ReceiveReportPage/IssueReportPage/EquipmentVerifyChecklistPage)
// carries its own current URL filters over verbatim -- this page performs
// no business logic of its own.
export function ReportPrintPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const [searchParams] = useSearchParams();
  const [fontsReady, setFontsReady] = useState(false);

  useEffect(() => {
    // Roadmap PR18C (design §9: "invokes the browser's native print dialog
    // only after data and fonts are ready"): document.fonts.ready resolves
    // once every @font-face declared in print.css (including the
    // self-hosted Noto Sans Thai) has either loaded or failed -- the Print
    // button stays disabled until then so a print never starts mid-swap
    // with a fallback font. Environments without the Font Loading API
    // (older browsers, some test environments) fall back to "ready
    // immediately" rather than blocking forever.
    if (typeof document === "undefined" || !("fonts" in document)) {
      setFontsReady(true);
      return;
    }
    let cancelled = false;
    document.fonts.ready.then(() => {
      if (!cancelled) setFontsReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const validReportId = isReportIdentity(reportId) ? reportId : null;

  // Roadmap PR18C: forwarded verbatim to GET /reports/{report_id}/print-data
  // (services/printReports.ts) -- this page does not decide which filter
  // keys are valid for which report identity. A filter that does not apply
  // to this report_id is rejected by the backend with a structured
  // INVALID_INPUT error (app.api.v1.reports._reject_inapplicable_print_data_filters),
  // surfaced below as a visible error rather than silently dropped or
  // producing a misleading document.
  const filters = Object.fromEntries(searchParams.entries());

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

  function handlePrint() {
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
            disabled={isLoading || isError || !fontsReady}
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

      {!isLoading && !isError && printDocument && <PrintDocumentView document={printDocument} />}
    </div>
  );
}
