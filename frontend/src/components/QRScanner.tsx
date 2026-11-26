import { BrowserQRCodeReader, IScannerControls } from "@zxing/browser";
import { DecodeHintType } from "@zxing/library";
import { useEffect, useRef, useState } from "react";

interface QRScannerProps {
  onScan: (text: string) => void;
  active: boolean;
}

// Rear camera at a decent resolution: small hospital QR stickers do not
// decode from the default (often front / low-res) stream on phones.
const CONSTRAINTS: MediaStreamConstraints = {
  audio: false,
  video: {
    facingMode: { ideal: "environment" },
    width: { ideal: 1280 },
    height: { ideal: 720 },
  },
};

export function QRScanner({ onScan, active }: QRScannerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  // Keep the latest callback in a ref so a parent re-render (which passes a
  // new inline callback) does not tear down and restart the camera before a
  // frame ever gets decoded.
  const onScanRef = useRef(onScan);
  useEffect(() => {
    onScanRef.current = onScan;
  }, [onScan]);

  useEffect(() => {
    if (!active || !videoRef.current) return;

    const hints = new Map<DecodeHintType, unknown>([[DecodeHintType.TRY_HARDER, true]]);
    const reader = new BrowserQRCodeReader(hints, { delayBetweenScanAttempts: 150 });
    let cancelled = false;
    let controls: IScannerControls | null = null;

    reader
      .decodeFromConstraints(CONSTRAINTS, videoRef.current, (result) => {
        if (cancelled) return;
        if (result) onScanRef.current(result.getText());
        // NotFoundException fires continuously while no code is in frame; ignore it.
      })
      .then((c) => {
        controls = c;
        if (cancelled) c.stop();
      })
      .catch(() => {
        if (!cancelled) setError("ไม่สามารถเข้าถึงกล้องได้ กรุณาอนุญาตการใช้งานกล้อง หรือค้นหาด้วยตนเอง");
      });

    return () => {
      cancelled = true;
      controls?.stop();
    };
  }, [active]);

  if (!active) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-black">
      {error ? (
        <p className="p-4 text-sm text-status-repair">{error}</p>
      ) : (
        <video ref={videoRef} className="aspect-square w-full object-cover" muted playsInline />
      )}
    </div>
  );
}
