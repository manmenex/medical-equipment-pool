import { useEffect, useRef, useState } from "react";

export type PrintFontsStatus = "pending" | "ready" | "error";

// Roadmap PR18C review (second round, PR18C-H1R): print readiness must be
// fail-closed -- a rejected `document.fonts.ready` must land on "error",
// never silently "ready" -- and tied to the specific document/render
// currently on screen. `currentDocument` should be the fetched
// ExportDocument itself (or `null` while none has loaded yet); every time
// it changes to a new value, this hook starts a brand-new check and any
// still-pending earlier check becomes stale.
//
// Staleness is enforced with a monotonically increasing generation token
// (`checkIdRef`): each check captures the token's value at the moment it
// starts, and only applies its result if that token is still the latest
// one when the check resolves or rejects. A native Promise cannot be
// cancelled, so this comparison -- not cancellation -- is what stops a
// superseded document's late completion from ever overriding the status of
// the document that replaced it.
export function usePrintFontsReady(currentDocument: unknown): {
  status: PrintFontsStatus;
  retry: () => void;
} {
  const [status, setStatus] = useState<PrintFontsStatus>("pending");
  const [retryToken, setRetryToken] = useState(0);
  const checkIdRef = useRef(0);

  useEffect(() => {
    if (!currentDocument) {
      setStatus("pending");
      return;
    }

    const checkId = ++checkIdRef.current;
    setStatus("pending");

    if (typeof document === "undefined" || !("fonts" in document)) {
      setStatus("ready");
      return;
    }

    document.fonts.ready.then(
      () => {
        if (checkIdRef.current === checkId) setStatus("ready");
      },
      () => {
        // Fail-closed: a rejected readiness check must never enable Print.
        if (checkIdRef.current === checkId) setStatus("error");
      }
    );
  }, [currentDocument, retryToken]);

  function retry() {
    setStatus("pending");
    setRetryToken((t) => t + 1);
  }

  return { status, retry };
}
