import { readFileSync } from "node:fs";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { PageTransition } from "./PageTransition";
import { ListSkeleton, PageSkeleton, Skeleton, StatCardsSkeleton } from "./Skeleton";

describe("Skeleton", () => {
  it("renders hidden blocks with accessible busy status and sr-only text", () => {
    const { container } = render(<ListSkeleton rows={3} />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("กำลังโหลด...")).toHaveClass("sr-only");
    expect(container.querySelectorAll(".skeleton")).toHaveLength(3);
  });

  it("renders the stat card and page variants", () => {
    const { container, unmount } = render(<StatCardsSkeleton count={4} />);
    expect(container.querySelectorAll(".skeleton")).toHaveLength(8);
    unmount();
    render(<PageSkeleton />);
    expect(screen.getByTestId("skeleton-group")).toBeInTheDocument();
    render(<Skeleton className="h-4" />);
  });
});

describe("PageTransition", () => {
  it("remounts (keys) on pathname change", () => {
    function Go() {
      const nav = useNavigate();
      return <button onClick={() => nav("/b")}>go</button>;
    }
    render(
      <MemoryRouter initialEntries={["/a"]}>
        <Go />
        <Routes>
          <Route path="*" element={<PageTransition><input data-testid="field" /></PageTransition>} />
        </Routes>
      </MemoryRouter>,
    );
    const first = screen.getByTestId("page-transition");
    expect(first).toHaveAttribute("data-path", "/a");
    const input = screen.getByTestId("field");
    screen.getByText("go").click();
    return screen.findByText("go").then(() => {
      const second = screen.getByTestId("page-transition");
      expect(second).toHaveAttribute("data-path", "/b");
      expect(second).not.toBe(first);
      expect(screen.getByTestId("field")).not.toBe(input);
    });
  });
});

describe("motion CSS", () => {
  const css = readFileSync(`${__dirname}/../index.css`, "utf8");
  it("gates animation behind prefers-reduced-motion: no-preference", () => {
    expect(css).toContain("@media (prefers-reduced-motion: no-preference)");
    const before = css.split("@media (prefers-reduced-motion: no-preference)")[0];
    expect(before).not.toMatch(/animation:/);
  });
  it("disables animation and transitions in print", () => {
    expect(css).toMatch(/@media print\s*{\s*\*,[\s\S]*animation: none !important/);
    expect(css).toMatch(/\.print-root \*[\s\S]*transition: none !important/);
  });
  it("never animates layout properties", () => {
    expect(css).not.toMatch(/@keyframes[^{]+{[^@]*\b(width|height|top|left)\s*:/);
  });
});
