import { useCallback, useRef, useState } from "react";

import { QRScanner } from "@/components/QRScanner";

interface ScanBarProps {
  onBcm: (text: string) => void;
  onQr: (raw: string) => void;
  busy?: boolean;
  /** QR scanning needs the camera + server (decision D1): hidden while offline. */
  offline?: boolean;
}

// Roadmap PR27/PR28: BCM text input + "สแกน QR" toggle (reuses the existing
// QRScanner). The scanner reports the same code on every frame, so repeats of
// one raw value inside a short window are dropped here.
export function ScanBar({ onBcm, onQr, busy, offline }: ScanBarProps) {
  const [text, setText] = useState("");
  const [scanning, setScanning] = useState(false);
  const last = useRef<{ raw: string; at: number } | null>(null);

  const submit = () => {
    const v = text.trim();
    if (!v) return;
    onBcm(v);
    setText("");
  };

  const handleScan = useCallback(
    (raw: string) => {
      const now = Date.now();
      if (last.current && last.current.raw === raw && now - last.current.at < 3000) return;
      last.current = { raw, at: now };
      onQr(raw);
    },
    [onQr],
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2">
        <input
          aria-label="รหัส BCM"
          placeholder="กรอกรหัส BCM แล้วกด Enter"
          value={text}
          autoComplete="off"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
          className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={submit}
          disabled={busy || !text.trim()}
          className="shrink-0 rounded-lg border border-[var(--border)] px-3 text-sm disabled:opacity-50"
        >
          เพิ่ม
        </button>
        {!offline && (
          <button
            type="button"
            aria-pressed={scanning}
            onClick={() => setScanning((s) => !s)}
            className="shrink-0 whitespace-nowrap rounded-lg bg-status-borrowed px-3 text-sm font-medium text-white"
          >
            {scanning ? "ปิดกล้อง" : "สแกน QR"}
          </button>
        )}
      </div>
      {!offline && scanning && <QRScanner active onScan={handleScan} />}
    </div>
  );
}
