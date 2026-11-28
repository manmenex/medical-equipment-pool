import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/imageCodeDecoder", () => ({
  decodeImageFile: async (f: File) => (f.name === "x.jpg" ? ["QR-X"] : []),
}));
vi.mock("@/components/QRScanner", () => ({ QRScanner: () => null }));

import { ScanBar } from "@/components/entry/ScanBar";

describe("ScanBar image scan", () => {
  it("sends decoded image codes to onQr and hides the button offline", async () => {
    const onQr = vi.fn();
    const { rerender } = render(<ScanBar onBcm={vi.fn()} onQr={onQr} />);
    fireEvent.change(screen.getByTestId("image-scan-input"), {
      target: { files: [new File(["a"], "x.jpg"), new File(["a"], "y.jpg")] },
    });
    await waitFor(() => expect(onQr).toHaveBeenCalledWith("QR-X"));
    expect(onQr).toHaveBeenCalledTimes(1);
    await screen.findByText("y.jpg");
    rerender(<ScanBar onBcm={vi.fn()} onQr={onQr} offline />);
    expect(screen.queryByText("สแกนจากรูปภาพ")).toBeNull();
  });
});
