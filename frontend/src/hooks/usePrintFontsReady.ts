import { useEffect, useRef, useState } from "react";

export type PrintFontsStatus = "pending" | "ready" | "error" | "unsupported";

// Roadmap PR18C (docs/design/PR18_PRINTING_EXPORT_PLAN.md §17): the exact
// family and weights print.css declares via @font-face -- kept here so the
// explicit document.fonts.load() calls below request precisely the faces
// this view actually uses, nothing more.
const PRINT_FONT_FAMILY = "Noto Sans Thai";
const PRINT_FONT_WEIGHTS = [400, 700] as const;
// A short probe string spanning both unicode-range subsets print.css splits
// each weight into (Thai script + Latin/digits), so document.fonts.load()
// requests both subsets rather than whichever one a shorter string happens
// to match.
const PRINT_FONT_PROBE_TEXT = "0123456789กขคง ABCabc";

function fontLoadingApiSupported(): boolean {
  // Roadmap PR18C review (fourth round, PR18C-H3): if the Font Loading API
  // itself -- or its `load()` method -- is unavailable, the browser cannot
  // be asked to verify font availability at all. Fail closed rather than
  // assume "ready" (the third round's fallback, corrected here).
  return typeof document !== "undefined" && "fonts" in document && typeof document.fonts?.load === "function";
}

type CompletedStatus = Exclude<PrintFontsStatus, "pending">;

// Roadmap PR18C review (fourth round, PR18C-H1R2/H2R2/H3): a corrected,
// spec-accurate and document-identity-safe replacement for the third
// round's implementation, which had two remaining defects:
//
// 1. (PR18C-H1) A resolved `document.fonts.load()` was treated as success
//    unconditionally. The promise resolves with the array of FontFaces that
//    actually matched and loaded -- an empty array is a valid, non-error
//    resolution that still means the requested font is not available. That
//    must fail closed exactly like a rejection does.
// 2. (PR18C-H2R2) Readiness was stored in a plain `status` state variable,
//    reset to "pending" only inside a `useEffect`. React does not reset
//    state just because a prop changed -- on the very first render after
//    `currentDocument` changes from document A to document B, `status`
//    still held A's "ready" result, because the effect that resets it only
//    runs after that render commits. A caller reading `status` during that
//    render window would see document A's readiness applied to document B.
//
// Both are fixed by never trusting a bare status value: the outcome of each
// completed check is tagged with the exact `currentDocument` it belongs to
// (`lastResultRef`), and the status returned to the caller is computed
// fresh on every render by comparing that tag against the `currentDocument`
// passed in *this* render -- not inside an effect, so there is no window
// where a stale document's result can be read as valid.
export function usePrintFontsReady(currentDocument: unknown): {
  status: PrintFontsStatus;
  retry: () => void;
} {
  const checkIdRef = useRef(0);
  const lastResultRef = useRef<{ documentKey: unknown; status: CompletedStatus } | null>(null);
  const [, forceRerender] = useState(0);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    if (!currentDocument) {
      return;
    }

    const checkId = ++checkIdRef.current;
    const documentKey = currentDocument;

    function complete(result: CompletedStatus) {
      // Staleness guard: only a check whose token is still the latest one
      // may record a result. A native Promise cannot be cancelled, so this
      // comparison -- not cancellation -- is what stops a superseded
      // document's late completion from ever being recorded at all.
      if (checkIdRef.current !== checkId) return;
      lastResultRef.current = { documentKey, status: result };
      forceRerender((n) => n + 1);
    }

    if (!fontLoadingApiSupported()) {
      complete("unsupported");
      return;
    }

    Promise.all(
      PRINT_FONT_WEIGHTS.map((weight) =>
        document.fonts.load(`${weight} 16px "${PRINT_FONT_FAMILY}"`, PRINT_FONT_PROBE_TEXT)
      )
    ).then(
      (loadedFaceLists) => {
        // Roadmap PR18C review (fourth round, PR18C-H1): a resolved promise
        // is not itself proof a font exists -- an empty result means no
        // face matching this family/weight/text was ever loaded.
        const loadedFaces = loadedFaceLists.flat();
        complete(loadedFaces.length > 0 ? "ready" : "error");
      },
      () => {
        // A genuine network/parse failure loading either weight.
        complete("error");
      }
    );
  }, [currentDocument, retryToken]);

  function retry() {
    // A retry discards the previous result for the current document
    // immediately, so the render right after calling retry() reflects
    // "pending" rather than continuing to show the stale error -- the same
    // synchronous, render-time guarantee the document-identity check above
    // relies on, not a state update the caller would have to wait for.
    lastResultRef.current = null;
    setRetryToken((t) => t + 1);
  }

  // Computed fresh on every render, directly from `currentDocument` -- see
  // the function-level comment above for why this must not be a state
  // variable that could still hold a previous document's result.
  let status: PrintFontsStatus = "pending";
  if (currentDocument && lastResultRef.current && lastResultRef.current.documentKey === currentDocument) {
    status = lastResultRef.current.status;
  }

  return { status, retry };
}
