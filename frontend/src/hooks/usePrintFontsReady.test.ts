import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePrintFontsReady } from "@/hooks/usePrintFontsReady";

// Roadmap PR18C review (third round, PR18C-H1R2): print readiness must be
// fail-closed (a genuine font-load failure must land on "error", never
// "ready") and tied to the specific document/render currently on screen (a
// stale check's late completion must never override a newer document's
// status). This is implemented via `document.fonts.load()`, whose returned
// promise the CSS Font Loading Module Level 3 spec defines to reject on a
// network/parse failure -- unlike `document.fonts.ready`, which is
// specified to never reject and so cannot detect a load failure at all
// (see the hook's own comment for the full explanation). These tests stub
// `document.fonts.load` as a controllable promise rather than
// `document.fonts.ready`.

let installedFontLoads: { resolve: () => void; reject: () => void }[] = [];

function installControllableFonts(): { resolve: () => void; reject: () => void; loadMock: ReturnType<typeof vi.fn> } {
  let resolve!: () => void;
  let reject!: () => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  const loadMock = vi.fn(() => promise);
  Object.defineProperty(document, "fonts", {
    configurable: true,
    value: { load: loadMock },
  });
  const controls = { resolve, reject, loadMock };
  installedFontLoads.push(controls);
  return controls;
}

beforeEach(() => {
  installedFontLoads = [];
});

afterEach(() => {
  delete (document as unknown as { fonts?: unknown }).fonts;
});

describe("usePrintFontsReady", () => {
  it("stays pending while no document has loaded", () => {
    const { result } = renderHook(() => usePrintFontsReady(null));
    expect(result.current.status).toBe("pending");
  });

  it("requests document.fonts.load() for both declared weights (400 and 700) of the print font, not document.fonts.ready", async () => {
    const { loadMock, resolve } = installControllableFonts();
    renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });

    expect(loadMock).toHaveBeenCalledWith('400 16px "Noto Sans Thai"', expect.any(String));
    expect(loadMock).toHaveBeenCalledWith('700 16px "Noto Sans Thai"', expect.any(String));

    resolve();
    await waitFor(() => {});
  });

  it("becomes ready once the current document's font-load check resolves", async () => {
    const fonts = installControllableFonts();
    const { result } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });
    expect(result.current.status).toBe("pending");

    fonts.resolve();
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });

  // Roadmap PR18C review (third round, PR18C-H1R2): `document.fonts.load()`
  // is the API that genuinely rejects on a network/parse failure -- this
  // proves the hook is fail-closed against that real rejection, not a
  // fabricated one.
  it("is fail-closed: a rejected document.fonts.load() lands on error, never ready", async () => {
    const fonts = installControllableFonts();
    const { result } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });

    fonts.reject();
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.status).not.toBe("ready");
  });

  it("does not let a stale document-A completion override a newer document-B's status", async () => {
    const fontsForA = installControllableFonts();
    const { result, rerender } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });

    // Document B supersedes document A before A's font check has resolved.
    const fontsForB = installControllableFonts();
    rerender({ doc: { id: "doc-b" } as unknown });
    expect(result.current.status).toBe("pending");

    // A's late completion must be ignored -- B is now current.
    fontsForA.resolve();
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.status).toBe("pending");

    // B's own check resolving is what may enable readiness.
    fontsForB.resolve();
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });

  it("does not let a stale document-A rejection mark a newer document-B as failed", async () => {
    const fontsForA = installControllableFonts();
    const { result, rerender } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });

    const fontsForB = installControllableFonts();
    rerender({ doc: { id: "doc-b" } as unknown });

    fontsForA.reject();
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.status).toBe("pending");

    fontsForB.resolve();
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });

  it("retry() re-runs the check for the current document and can recover from error", async () => {
    const fonts = installControllableFonts();
    const { result } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });

    fonts.reject();
    await waitFor(() => expect(result.current.status).toBe("error"));

    const retryFonts = installControllableFonts();
    result.current.retry();
    await waitFor(() => expect(result.current.status).toBe("pending"));

    retryFonts.resolve();
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });
});
