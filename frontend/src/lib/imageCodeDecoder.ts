import { BrowserQRCodeReader } from "@zxing/browser";
import { DecodeHintType } from "@zxing/library";

// Decodes a code from a photo entirely in the browser. Nothing is uploaded,
// stored or logged. zxing's QR reader finds one code per image (the library
// ships no multi-QR reader), so each photo yields at most one code.
//
// Memory: a 48 MP photo is never decoded at full size. Each pass asks the
// browser for a bitmap already resized to a capped long side
// (createImageBitmap resize options), or, where those are unsupported, draws
// the <img> straight into a capped canvas. Pass 1 caps at FAST_SIDE; the
// retry caps at RETRY_SIDE. Everything is released after each image.
export const FAST_SIDE = 2000;
export const RETRY_SIDE = 3000;

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("image load failed"));
    img.src = url;
  });
}

async function resizedSource(
  img: HTMLImageElement,
  file: Blob,
  w: number,
  h: number,
): Promise<{ source: CanvasImageSource; close: () => void }> {
  const resized = w !== img.naturalWidth || h !== img.naturalHeight;
  if (typeof createImageBitmap === "function") {
    try {
      const bmp = resized
        ? await createImageBitmap(file, { resizeWidth: w, resizeHeight: h, resizeQuality: "high" })
        : await createImageBitmap(file);
      return { source: bmp, close: () => bmp.close() };
    } catch {
      // resize options unsupported: fall through to the <img> path.
    }
  }
  return { source: img, close: () => undefined };
}

async function decodePass(
  reader: BrowserQRCodeReader,
  img: HTMLImageElement,
  file: Blob,
  cap: number,
): Promise<string | null> {
  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  const scale = Math.min(1, cap / Math.max(nw, nh));
  const w = Math.max(1, Math.round(nw * scale));
  const h = Math.max(1, Math.round(nh * scale));
  const { source, close } = await resizedSource(img, file, w, h);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  try {
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(source, 0, 0, w, h);
    return reader.decodeFromCanvas(canvas).getText();
  } catch {
    return null;
  } finally {
    canvas.width = 0;
    canvas.height = 0;
    close();
  }
}

/** Returns the decoded codes of one image (empty when nothing readable). */
export async function decodeImageFile(file: Blob): Promise<string[]> {
  const hints = new Map<DecodeHintType, unknown>([[DecodeHintType.TRY_HARDER, true]]);
  const reader = new BrowserQRCodeReader(hints);
  const url = URL.createObjectURL(file);
  let img: HTMLImageElement | null = null;
  try {
    img = await loadImage(url);
    const long = Math.max(img.naturalWidth, img.naturalHeight);
    const caps = long > FAST_SIDE ? [FAST_SIDE, RETRY_SIDE] : [FAST_SIDE];
    for (const cap of caps) {
      const text = await decodePass(reader, img, file, cap);
      if (text) return [text];
    }
    return [];
  } catch {
    return [];
  } finally {
    if (img) img.src = "";
    URL.revokeObjectURL(url);
  }
}
