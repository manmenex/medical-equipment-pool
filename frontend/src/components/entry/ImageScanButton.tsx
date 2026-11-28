import { useRef, useState } from "react";

interface ImageScanButtonProps {
  /** Same handler a camera scan uses, so lookup/duplicate/offline rules apply. */
  onScan: (text: string) => void;
  /** Decoder is injectable for tests; defaults to the lazy-loaded zxing one. */
  decode?: (file: File) => Promise<string[]>;
}

interface Summary {
  codes: number;
  total: number;
  failed: string[];
}

async function defaultDecode(file: File): Promise<string[]> {
  const mod = await import("@/lib/imageCodeDecoder");
  return mod.decodeImageFile(file);
}

// Decode photos one at a time (phones freeze with parallel big bitmaps).
// Files are only read in memory; nothing is uploaded or persisted.
export function ImageScanButton({ onScan, decode = defaultDecode }: ImageScanButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);

  const handleFiles = async (list: FileList | null) => {
    const files = list ? Array.from(list) : [];
    if (inputRef.current) inputRef.current.value = "";
    if (files.length === 0) return;
    setSummary(null);
    const seen = new Set<string>();
    const failed: string[] = [];
    let codes = 0;
    for (let i = 0; i < files.length; i++) {
      setProgress({ done: i + 1, total: files.length });
      let found: string[] = [];
      try {
        found = await decode(files[i]);
      } catch {
        found = [];
      }
      if (found.length === 0) failed.push(files[i].name);
      for (const raw of found) {
        if (seen.has(raw)) continue;
        seen.add(raw);
        codes++;
        onScan(raw);
      }
    }
    setProgress(null);
    setSummary({ codes, total: files.length, failed });
  };

  return (
    <div className="flex flex-col gap-1">
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        data-testid="image-scan-input"
        onChange={(e) => void handleFiles(e.target.files)}
      />
      <button
        type="button"
        disabled={progress !== null}
        onClick={() => inputRef.current?.click()}
        className="min-h-11 rounded-lg border border-[var(--border)] px-3 text-sm disabled:opacity-50"
      >
        สแกนจากรูปภาพ
      </button>
      {progress && (
        <p role="status" className="text-sm text-[var(--text-muted)]">
          กำลังอ่าน {progress.done}/{progress.total}
        </p>
      )}
      {summary && (
        <div role="status" className="text-sm">
          <p>
            อ่านได้ {summary.codes} รหัส จาก {summary.total} รูป · อ่านไม่ได้ {summary.failed.length} รูป
          </p>
          {summary.failed.length > 0 && (
            <ul className="list-disc pl-5 text-status-repair">
              {summary.failed.map((n, i) => (
                <li key={`${n}-${i}`} className="break-all">
                  {n}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
