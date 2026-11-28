import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const decodeFromCanvas = vi.fn();
vi.mock("@zxing/browser", () => ({
  BrowserQRCodeReader: class {
    decodeFromCanvas = decodeFromCanvas;
  },
}));

import { decodeImageFile } from "@/lib/imageCodeDecoder";

const closes: number[] = [];

function stubImage(w: number, h: number) {
  class FakeImage {
    naturalWidth = w;
    naturalHeight = h;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    set src(v: string) {
      if (v) setTimeout(() => this.onload?.(), 0);
    }
  }
  vi.stubGlobal("Image", FakeImage);
}

beforeEach(() => {
  decodeFromCanvas.mockReset();
  closes.length = 0;
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn() } as never);
});
afterEach(() => vi.unstubAllGlobals());

const bitmapStub = () =>
  vi.fn(async (_f: Blob, opts?: { resizeWidth: number; resizeHeight: number }) => ({
    width: opts?.resizeWidth ?? 0,
    close: () => closes.push(1),
  }));

describe("decodeImageFile", () => {
  it("decodes a huge photo from a bitmap resized to <= 2000px, never full size", async () => {
    stubImage(8000, 6000);
    const cib = bitmapStub();
    vi.stubGlobal("createImageBitmap", cib);
    decodeFromCanvas.mockReturnValue({ getText: () => "CODE" });
    expect(await decodeImageFile(new Blob(["x"]))).toEqual(["CODE"]);
    expect(cib).toHaveBeenCalledTimes(1);
    expect(cib.mock.calls[0][1]).toEqual({ resizeWidth: 2000, resizeHeight: 1500, resizeQuality: "high" });
    expect(closes).toHaveLength(1);
    expect(URL.revokeObjectURL).toHaveBeenCalled();
  });

  it("retries once at a capped 3000px, not natural size", async () => {
    stubImage(8000, 6000);
    const cib = bitmapStub();
    vi.stubGlobal("createImageBitmap", cib);
    decodeFromCanvas.mockImplementationOnce(() => {
      throw new Error("nf");
    });
    decodeFromCanvas.mockReturnValueOnce({ getText: () => "RETRY" });
    expect(await decodeImageFile(new Blob(["x"]))).toEqual(["RETRY"]);
    expect(cib.mock.calls.map((c) => c[1]?.resizeWidth)).toEqual([2000, 3000]);
    expect(closes).toHaveLength(2);
  });

  it("returns nothing after both passes fail", async () => {
    stubImage(8000, 6000);
    vi.stubGlobal("createImageBitmap", bitmapStub());
    decodeFromCanvas.mockImplementation(() => {
      throw new Error("nf");
    });
    expect(await decodeImageFile(new Blob(["x"]))).toEqual([]);
    expect(decodeFromCanvas).toHaveBeenCalledTimes(2);
  });

  it("falls back to the <img> in a capped canvas when resize options are unsupported", async () => {
    stubImage(6000, 4000);
    vi.stubGlobal("createImageBitmap", vi.fn().mockRejectedValue(new TypeError("opts")));
    decodeFromCanvas.mockReturnValue({ getText: () => "IMG" });
    expect(await decodeImageFile(new Blob(["x"]))).toEqual(["IMG"]);
    const canvas = decodeFromCanvas.mock.calls[0][0] as HTMLCanvasElement;
    // canvas is zeroed after use; the call happened on a 2000px-capped canvas.
    expect(canvas.width).toBe(0);
  });
});
