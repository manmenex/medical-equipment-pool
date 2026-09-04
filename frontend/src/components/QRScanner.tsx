import { BrowserQRCodeReader, IScannerControls } from "@zxing/browser";
import { useEffect, useRef, useState } from "react";

interface QRScannerProps {
  onScan: (text: string) => void;
  active: boolean;
}

export function QRScanner({ onScan, active }: QRScannerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const controlsRef = useRef<IScannerControls | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active || !videoRef.current) return;

    const reader = new BrowserQRCodeReader();
    let cancelled = false;

    reader
      .decodeFromVideoDevice(undefined, videoRef.current, (result, err, controls) => {
        controlsRef.current = controls;
        if (cancelled) return;
        if (result) {
          onScan(result.getText());
        }
        // NotFoundException fires continuously while no code is in frame; ignore it.
      })
      .catch(() => setError("ไม่สามารถเข้าถึงกล้องได้ กรุณาอนุญาตการใช้งานกล้อง หรือค้นหาด้วยตนเอง"));

    return () => {
      cancelled = true;
      controlsRef.current?.stop();
    };
  }, [active, onScan]);

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
