import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ImageScanButton } from "@/components/entry/ImageScanButton";

const file = (n: string) => new File(["x"], n, { type: "image/jpeg" });

describe("ImageScanButton", () => {
  it("routes decoded codes through onScan, dedupes, and summarises failures", async () => {
    const onScan = vi.fn();
    const decode = vi.fn(async (f: File) => {
      if (f.name === "a.jpg") return ["BCM1"];
      if (f.name === "b.jpg") return ["BCM1"]; // duplicate
      if (f.name === "c.jpg") return [];
      return ["BCM2"];
    });
    render(<ImageScanButton onScan={onScan} decode={decode} />);
    expect(screen.getByText("สแกนจากรูปภาพ")).toBeTruthy();
    const input = screen.getByTestId("image-scan-input") as HTMLInputElement;
    expect(input.multiple).toBe(true);
    expect(input.accept).toBe("image/*");
    fireEvent.change(input, { target: { files: [file("a.jpg"), file("b.jpg"), file("c.jpg"), file("d.jpg")] } });
    await waitFor(() => expect(screen.getByText(/อ่านได้ 2 รหัส จาก 4 รูป · อ่านไม่ได้ 1 รูป/)).toBeTruthy());
    expect(onScan.mock.calls.map((c) => c[0])).toEqual(["BCM1", "BCM2"]);
    expect(screen.getByText("c.jpg")).toBeTruthy();
    expect(decode).toHaveBeenCalledTimes(4);
  });

  it("awaits each scan and lists every blocked code in the summary", async () => {
    const order: string[] = [];
    const onScan = vi.fn(async (code: string) => {
      order.push(`start ${code}`);
      await new Promise((r) => setTimeout(r, 5));
      order.push(`end ${code}`);
      if (code === "DUP") return "⚠ DUP สแกนซ้ำ";
      if (code === "OUT") return "ยังไม่ได้ถูกจ่ายออก ต้องเลือกสลับไปเบิก";
      return undefined;
    });
    const decode = async (f: File) => [f.name.replace(".jpg", "")];
    render(<ImageScanButton onScan={onScan} decode={decode} />);
    fireEvent.change(screen.getByTestId("image-scan-input"), {
      target: { files: [file("OK.jpg"), file("DUP.jpg"), file("OUT.jpg")] },
    });
    await waitFor(() => expect(screen.getByText("ต้องตรวจเอง")).toBeTruthy());
    expect(screen.getByText(/DUP · ⚠ DUP สแกนซ้ำ/)).toBeTruthy();
    expect(screen.getByText(/OUT · ยังไม่ได้ถูกจ่ายออก/)).toBeTruthy();
    expect(order).toEqual(["start OK", "end OK", "start DUP", "end DUP", "start OUT", "end OUT"]);
  });

  it("treats a decoder error as a failed image and persists nothing", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const onScan = vi.fn();
    render(
      <ImageScanButton
        onScan={onScan}
        decode={async () => {
          throw new Error("boom");
        }}
      />,
    );
    fireEvent.change(screen.getByTestId("image-scan-input"), { target: { files: [file("bad.jpg")] } });
    await waitFor(() => expect(screen.getByText(/อ่านไม่ได้ 1 รูป/)).toBeTruthy());
    expect(onScan).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
  });
});
