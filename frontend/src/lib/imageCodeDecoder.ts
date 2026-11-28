import { BrowserQRCodeReader } from "@zxing/browser";
import { DecodeHintType } from "@zxing/library";

// Decodes a code from a photo entirely in the browser. The image is drawn to
// a transient canvas and released straight away: nothing is uploaded, stored
// or logged. zxing's QR reader finds one code per image (the library ships no
// multi-QR reader), so each photo yields at most one code.
const MAX_SIDE = 2000;

async function loadBitmap(file: Blob): Promise<{ source: CanvasImageSource; w: number; h: number; close: () => void }> {
  if (typeof createImageBitmap === "function") {
    const bmp = await createImageBitmap(file);
    return { source: bmp, w: bmp.width, h: bmp.height, close: () => bmp.close() };
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return { source: img, w: img.naturalWidth, h: img.naturalHeight, close: () => undefined };
  } finally {
    URL.revokeObjectURL(url);
  }
}

function tryDecode(reader: BrowserQRCodeReader, source: CanvasImageSource, w: number, h: number, scale: number): string | null {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(w * scale));
  canvas.height = Math.max(1, Math.round(h * scale));
  try {
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    return reader.decodeFromCanvas(canvas).getText();
  } catch {
    return null;
  } finally {
    canvas.width = 0;
    canvas.height = 0;
  }
}

/** Returns the decoded codes of one image (empty when nothing readable). */
export async function decodeImageFile(file: Blob): Promise<string[]> {
  const hints = new Map<DecodeHintType, unknown>([[DecodeHintType.TRY_HARDER, true]]);
  const reader = new BrowserQRCodeReader(hints);
  let bmp;
  try {
    bmp = await loadBitmap(file);
  } catch {
    return [];
  }
  try {
    const long = Math.max(bmp.w, bmp.h);
    // Very large photos: try the downscaled copy first (fast), then natural size.
    const scales = long > MAX_SIDE ? [MAX_SIDE / long, 1] : [1];
    for (const s of scales) {
      const text = tryDecode(reader, bmp.source, bmp.w, bmp.h, s);
      if (text) return [text];
    }
    return [];
  } finally {
    bmp.close();
  }
}
