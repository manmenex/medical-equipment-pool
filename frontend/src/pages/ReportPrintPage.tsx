import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { PrintDocumentView } from "@/components/print/PrintDocumentView";
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
// business logic of its own; it only selects the whitelisted subset of
// those filters this report identity actually accepts (see
// services/printReports.ts's buildPrintDataFilters, review 4837997016 H2).
export function ReportPrintPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const [searchParams] = useSearchParams();
  const [fontsReady, setFontsReady] = useState(false);

  const validReportId = isReportIdentity(reportId) ? reportId : null;

  // Roadmap PR18C review 4837997016 (H2): an explicit, per-report-identity
  // whitelist -- never the raw `URLSearchParams`/`location.search` forwarded
  // as-is. Forwarding everything would also drag along `cursor`, `limit`, or
  // any future UI-only query param the on-screen report page might someday
  // add, none of which this route accepts or should ever receive.
  const filters = validReportId ? buildPrintDataFilters(validReportId, searchParams) : {};

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

  useEffect(() => {
    // Roadmap PR18C review 4837997016 (H1): readiness is "report loaded AND
    // rendered AND document.fonts.ready" -- deliberately not
    // document.fonts.ready alone, started at mount. Subscribing to
    // document.fonts.ready before the print content (and its "Noto Sans
    // Thai" font-family) has actually rendered into the DOM would let the
    // browser resolve "ready" before it has even discovered that this font
    // is required by anything on the page, defeating the entire point of
    // this gate (design §9: "invokes the browser's native print dialog only
    // after data and fonts are ready"). This effect depends on
    // `printDocument`, so it only starts once that value is set -- which
    // React guarantees happens after the render that includes
    // <PrintDocumentView> below has committed to the DOM.
    if (!printDocument) {
      return;
    }
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
  }, [printDocument]);

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

  const isReady = !isLoading && !isError && !!printDocument && fontsReady;

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

      {!isLoading && !isError && printDocument && <PrintDocumentView document={printDocument} />}
    </div>
  );
}
