import { useEffect, useRef, useState } from "react";

export type PrintFontsStatus = "pending" | "ready" | "error";

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

// Roadmap PR18C review (third round, PR18C-H1R2): a corrected, spec-accurate
// replacement for the second round's fail-closed attempt, which subscribed
// to `document.fonts.ready` and treated its rejection as a font-load
// failure. That is not how the Font Loading API is specified to behave:
// per CSS Font Loading Module Level 3, `FontFaceSet.ready` "is not
// rejected" -- it only ever fulfills, once whatever loading the browser has
// already discovered is needed has settled, successfully or not. A
// `.then(onFulfilled, onReject)` on that promise can never actually reach
// its reject branch in a real browser, so it cannot detect a genuine font
// load failure no matter how it's written.
//
// `FontFaceSet.load(font, text)` is the API the spec defines to reject on a
// genuine network/parse failure for the specific font(s) requested (MDN:
// "the promise... rejects... if network errors cause the loading to
// fail"). Calling it explicitly, rather than waiting for the browser to
// discover the font is needed from rendered content, also removes the
// original (first-round) timing concern entirely -- there is no "before the
// content has rendered" race to guard against when the load is requested
// directly, so this hook no longer depends on being started only after
// <PrintDocumentView> has committed to the DOM (though it still only starts
// once `currentDocument` is set, since there is nothing to load for before
// then).
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

    if (typeof document === "undefined" || !("fonts" in document) || !("load" in document.fonts)) {
      setStatus("ready");
      return;
    }

    // Staleness is enforced with a monotonically increasing generation
    // token (`checkIdRef`): each check captures the token's value at the
    // moment it starts, and only applies its result if that token is still
    // the latest one when the check resolves or rejects. A native Promise
    // cannot be cancelled, so this comparison -- not cancellation -- is
    // what stops a superseded document's late completion from ever
    // overriding the status of the document that replaced it.
    Promise.all(
      PRINT_FONT_WEIGHTS.map((weight) =>
        document.fonts.load(`${weight} 16px "${PRINT_FONT_FAMILY}"`, PRINT_FONT_PROBE_TEXT)
      )
    ).then(
      () => {
        if (checkIdRef.current === checkId) setStatus("ready");
      },
      () => {
        // Fail-closed: a genuine network/parse failure loading either
        // weight must never enable Print.
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
