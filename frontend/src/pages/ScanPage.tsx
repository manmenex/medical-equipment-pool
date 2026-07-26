import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";

import { BcmSearchInput } from "@/components/BcmSearchInput";
import { QRScanner } from "@/components/QRScanner";
import { apiErrorMessage } from "@/services/api";
import { resolveEquipmentByQr } from "@/services/equipment";
import type { BcmSuggestion } from "@/types";

// Dashboard & Equipment Status (unnumbered Post-PR11 frontend follow-up): a
// neutral "scan to check status" quick action, distinct from the dispatch
// (BorrowPage) and receipt
// (ReturnPage) entry points -- this page never commits to either workflow,
// it only resolves the scanned/searched equipment and opens its detail
// view. Reuses QRScanner, BcmSearchInput, and resolveEquipmentByQr exactly
// as BorrowPage/ReturnPage already do; no QR resolution logic changed.
export function ScanPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  const resolveFromQr = useCallback(
    async (rawValue: string) => {
      setError(null);
      try {
        const eq = await resolveEquipmentByQr(rawValue);
        navigate(`/equipment/${eq.id}`);
      } catch (err) {
        setError(apiErrorMessage(err, "ไม่พบเครื่องมือจาก QR ที่สแกน"));
      }
    },
    [navigate]
  );

  const handleBcmSelect = useCallback(
    (suggestion: BcmSuggestion) => {
      navigate(`/equipment/${suggestion.id}`);
    },
    [navigate]
  );

  return (
    <div className="mx-auto flex max-w-sm flex-col gap-4">
      <h1 className="text-lg font-semibold">สแกน QR</h1>
      <QRScanner active onScan={resolveFromQr} />
      <p className="text-center text-sm text-[var(--text-muted)]">หรือค้นหาด้วยรหัส BCM</p>
      <BcmSearchInput onSelect={handleBcmSelect} />
      {error && <p className="text-sm text-status-repair">{error}</p>}
    </div>
  );
}
