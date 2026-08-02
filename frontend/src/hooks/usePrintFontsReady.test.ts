import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePrintFontsReady } from "@/hooks/usePrintFontsReady";

// Roadmap PR18C review (second round, PR18C-H1R): print readiness must be
// fail-closed (a rejected check must land on "error", never "ready") and
// tied to the specific document/render currently on screen (a stale
// check's late completion must never override a newer document's status).

let installedFontFaceSets: { resolve: () => void; reject: () => void }[] = [];

function installControllableFonts(): { resolve: () => void; reject: () => void } {
  let resolve!: () => void;
  let reject!: () => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  Object.defineProperty(document, "fonts", {
    configurable: true,
    value: { ready: promise },
  });
  const controls = { resolve, reject };
  installedFontFaceSets.push(controls);
  return controls;
}

beforeEach(() => {
  installedFontFaceSets = [];
});

afterEach(() => {
  delete (document as unknown as { fonts?: unknown }).fonts;
});

describe("usePrintFontsReady", () => {
  it("stays pending while no document has loaded", () => {
    const { result } = renderHook(() => usePrintFontsReady(null));
    expect(result.current.status).toBe("pending");
  });

  it("becomes ready once the current document's font check resolves", async () => {
    const fonts = installControllableFonts();
    const { result } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });
    expect(result.current.status).toBe("pending");

    fonts.resolve();
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });

  it("is fail-closed: a rejected font check lands on error, never ready", async () => {
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
