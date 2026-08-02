import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePrintFontsReady } from "@/hooks/usePrintFontsReady";

// Roadmap PR18C review (fourth round, PR18C-H1/H2R2/H3): print readiness
// must be fail-closed in every dimension the Font Loading API actually
// exposes -- a genuine load rejection, an empty (but resolved) FontFace
// result, an unsupported browser, and a stale or superseded document -- and
// none of that may depend on `document.fonts.ready`, which the CSS Font
// Loading Module Level 3 spec defines to never reject at all.

let installedFontLoads: { resolve: (faces?: unknown[]) => void; reject: () => void }[] = [];

// Defaults to resolving with one stub FontFace so existing tests that only
// care about "a real success" don't need to know about the empty-array
// case; PR18C-H1's own test resolves with `[]` explicitly.
function installControllableFonts(): {
  resolve: (faces?: unknown[]) => void;
  reject: () => void;
  loadMock: ReturnType<typeof vi.fn>;
} {
  let resolve!: (faces?: unknown[]) => void;
  let reject!: () => void;
  const promise = new Promise<unknown[]>((res, rej) => {
    resolve = (faces = [{}]) => res(faces);
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

  it("becomes ready once document.fonts.load() resolves with one or more matching faces", async () => {
    const fonts = installControllableFonts();
    const { result } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });
    expect(result.current.status).toBe("pending");

    fonts.resolve([{ family: "Noto Sans Thai" }]);
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });

  // Roadmap PR18C review (fourth round, PR18C-H1): a resolved promise is not
  // itself proof a font exists -- document.fonts.load() resolving with an
  // empty array means nothing matched, and must fail closed exactly like a
  // genuine rejection.
  it("fails closed when document.fonts.load() resolves with an empty array (no matching face)", async () => {
    const fonts = installControllableFonts();
    const { result } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });

    fonts.resolve([]);
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.status).not.toBe("ready");
  });

  it("is fail-closed: a rejected document.fonts.load() lands on error, never ready", async () => {
    const fonts = installControllableFonts();
    const { result } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });

    fonts.reject();
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.status).not.toBe("ready");
  });

  // Roadmap PR18C review (fourth round, PR18C-H3): the Font Loading API
  // itself may be entirely unavailable -- this must fail closed too, with a
  // distinct status the page renders as an unsupported-browser message
  // (never silently treated as "ready").
  it("fails closed as unsupported when document.fonts is absent", async () => {
    // No installControllableFonts() call -- jsdom's document has no .fonts.
    const { result } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });

    await waitFor(() => expect(result.current.status).toBe("unsupported"));
  });

  it("fails closed as unsupported when document.fonts.load is absent", async () => {
    Object.defineProperty(document, "fonts", { configurable: true, value: {} });
    const { result } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });

    await waitFor(() => expect(result.current.status).toBe("unsupported"));
  });

  // Roadmap PR18C review (fourth round, PR18C-H2R2): a document transition
  // must fail closed immediately on the new document's first render -- not
  // only after an effect has had a chance to run. This is the core defect:
  // a plain `status` state variable, reset only inside useEffect, would
  // still read "ready" (document A's result) on this very first render.
  it("does not let document A's ready status leak into document B's very first render", async () => {
    const fontsForA = installControllableFonts();
    const { result, rerender } = renderHook(({ doc }) => usePrintFontsReady(doc), {
      initialProps: { doc: { id: "doc-a" } as unknown },
    });

    fontsForA.resolve();
    await waitFor(() => expect(result.current.status).toBe("ready"));

    installControllableFonts();
    rerender({ doc: { id: "doc-b" } as unknown });

    // No `waitFor`/`act` flush here on purpose: this assertion checks the
    // synchronous render result immediately after the prop change, before
    // any effect has run.
    expect(result.current.status).toBe("pending");
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
