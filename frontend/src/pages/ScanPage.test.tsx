import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ScanPage } from "@/pages/ScanPage";
import type { BcmSuggestion, Equipment } from "@/types";

// Roadmap PR12 (Dashboard & Equipment Status): ScanPage is the destination
// for the dashboard's "สแกน QR" quick action -- a neutral equipment lookup
// that resolves a scan/search to the existing EquipmentDetailPage, never
// committing to dispatch or receipt. Reuses resolveEquipmentByQr exactly as
// BorrowPage/ReturnPage already do; no QR resolution logic is under test
// here, only that this page wires the existing pieces together correctly.
const equipment: Equipment = {
  id: "eq-1",
  asset_number: "AST-1",
  serial_number: null,
  equipment_name: "Infusion Pump",
  category_id: null,
  brand: null,
  model: null,
  department_owner_id: null,
  current_location_id: null,
  status: "available_at_pool",
  bcm_code: null,
  pm_due_date: null,
  cal_due_date: null,
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
};

const resolveEquipmentByQr = vi.fn();

vi.mock("@/services/equipment", () => ({
  resolveEquipmentByQr: (...args: unknown[]) => resolveEquipmentByQr(...args),
}));

let scannedValue: string | null = null;
vi.mock("@/components/QRScanner", () => ({
  QRScanner: ({ onScan }: { onScan: (value: string) => void; active: boolean }) => (
    <button type="button" onClick={() => onScan(scannedValue ?? "raw-qr-value")}>
      simulate-scan
    </button>
  ),
}));

let bcmSelection: BcmSuggestion | null = null;
vi.mock("@/components/BcmSearchInput", () => ({
  BcmSearchInput: ({ onSelect }: { onSelect: (suggestion: BcmSuggestion) => void }) => (
    <button type="button" onClick={() => bcmSelection && onSelect(bcmSelection)}>
      simulate-bcm-select
    </button>
  ),
}));

beforeEach(() => {
  scannedValue = null;
  bcmSelection = null;
});

afterEach(() => {
  vi.clearAllMocks();
});

function EquipmentDetailStub() {
  const location = useLocation();
  return <div>equipment detail: {location.pathname}</div>;
}

function renderScanPage() {
  return render(
    <MemoryRouter initialEntries={["/scan"]}>
      <Routes>
        <Route path="/scan" element={<ScanPage />} />
        <Route path="/equipment/:id" element={<EquipmentDetailStub />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("ScanPage (Roadmap PR12 quick action destination)", () => {
  it("renders the page heading and both scan/search entry points", () => {
    renderScanPage();
    expect(screen.getByRole("heading", { name: "สแกน QR" })).toBeInTheDocument();
    expect(screen.getByText("simulate-scan")).toBeInTheDocument();
    expect(screen.getByText("simulate-bcm-select")).toBeInTheDocument();
  });

  it("navigates to the equipment detail page after a successful QR resolve", async () => {
    scannedValue = "raw-qr-payload";
    resolveEquipmentByQr.mockResolvedValue(equipment);
    const user = userEvent.setup();
    renderScanPage();

    await user.click(screen.getByText("simulate-scan"));

    await waitFor(() => expect(resolveEquipmentByQr).toHaveBeenCalledWith("raw-qr-payload"));
    await waitFor(() => expect(screen.getByText(/equipment detail: \/equipment\/eq-1/)).toBeInTheDocument());
  });

  it("navigates to the equipment detail page directly from a BCM suggestion, without an extra lookup", async () => {
    bcmSelection = { id: "eq-2", bcm_code: "BCM-2" };
    const user = userEvent.setup();
    renderScanPage();

    await user.click(screen.getByText("simulate-bcm-select"));

    await waitFor(() => expect(screen.getByText(/equipment detail: \/equipment\/eq-2/)).toBeInTheDocument());
    expect(resolveEquipmentByQr).not.toHaveBeenCalled();
  });

  it("shows an error and stays on the scan page when QR resolution fails", async () => {
    scannedValue = "bad-payload";
    resolveEquipmentByQr.mockRejectedValue({ isAxiosError: true, response: { status: 404, data: {} } });
    const user = userEvent.setup();
    renderScanPage();

    await user.click(screen.getByText("simulate-scan"));

    await waitFor(() => expect(screen.getByText("ไม่พบเครื่องมือจาก QR ที่สแกน")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "สแกน QR" })).toBeInTheDocument();
  });
});
