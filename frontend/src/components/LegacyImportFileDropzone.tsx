import { useRef, useState } from "react";

import { formatFileSize, isAllowedImportFile, IMPORT_FILE_TYPE_ERROR_MESSAGE } from "@/utils/legacyImportLabels";

interface LegacyImportFileDropzoneProps {
  file: File | null;
  onSelect: (file: File) => void;
  onRemove: () => void;
  accept?: string;
}

const DEFAULT_ACCEPT = ".xlsx";

// PR19B "File selection skeleton": browse button, drag-and-drop visual
// state, selected filename/size, remove/replace. Deliberately never
// uploads, parses, or inspects file content -- only File.name/size/type are
// ever read (task scope: "No real file processing").
//
// File-type enforcement: the `accept` attribute on the underlying
// <input type="file"> is a usability hint only -- browsers do not apply it
// to drag-and-drop, and a user can still pick a non-matching file via "all
// files" in the native picker. `isAllowedImportFile` (checked on both the
// picker and drag/drop paths) is the actual gate; a rejected file never
// reaches `onSelect`, so the dropzone stays in its empty/selectable state
// and the user can immediately try another file.
export function LegacyImportFileDropzone({ file, onSelect, onRemove, accept = DEFAULT_ACCEPT }: LegacyImportFileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [typeError, setTypeError] = useState<string | null>(null);

  function openFileDialog() {
    inputRef.current?.click();
  }

  function handleFiles(fileList: FileList | null) {
    const selected = fileList?.[0];
    if (!selected) return;
    if (!isAllowedImportFile(selected)) {
      setTypeError(IMPORT_FILE_TYPE_ERROR_MESSAGE);
      return;
    }
    setTypeError(null);
    onSelect(selected);
  }

  if (file) {
    return (
      <div className="surface flex items-center justify-between gap-3 rounded-xl border p-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{file.name}</p>
          <p className="text-xs text-[var(--text-muted)]">{formatFileSize(file.size)}</p>
        </div>
        <button
          type="button"
          onClick={() => {
            setTypeError(null);
            onRemove();
          }}
          className="shrink-0 rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium"
        >
          เปลี่ยนไฟล์
        </button>
      </div>
    );
  }

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-describedby="legacy-import-file-hint"
        onClick={openFileDialog}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            openFileDialog();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={`flex min-h-32 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center transition ${
          isDragging ? "border-status-borrowed bg-status-borrowed/5" : "border-[var(--border)]"
        }`}
      >
        <span className="text-2xl" aria-hidden="true">
          📄
        </span>
        <p className="text-sm font-medium">ลากไฟล์มาวางที่นี่ หรือกดเพื่อเลือกไฟล์</p>
        <p id="legacy-import-file-hint" className="text-xs text-[var(--text-muted)]">
          รองรับไฟล์ {accept} เท่านั้น
        </p>
      </div>
      {typeError && (
        <p role="alert" className="mt-2 text-sm text-status-repair">
          {typeError}
        </p>
      )}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        aria-label="เลือกไฟล์สำหรับนำเข้าข้อมูลเดิม"
        className="sr-only"
        onChange={(e) => {
          handleFiles(e.target.files);
          // Reset so re-selecting the same rejected filename re-fires
          // onChange (browsers otherwise suppress a repeat-value event).
          e.target.value = "";
        }}
      />
    </div>
  );
}
