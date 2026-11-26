import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourceBadge, sourceBadgeLabel } from "@/components/SourceBadge";

// Roadmap PR33 (D14): "DEMO" / "ยืม" badges; pool shows nothing.
describe("SourceBadge", () => {
  it("shows DEMO for demo devices", () => {
    render(<SourceBadge source="demo" />);
    expect(screen.getByTestId("source-badge")).toHaveTextContent("DEMO");
  });

  it("shows ยืม for loaned devices", () => {
    render(<SourceBadge source="loan" />);
    expect(screen.getByTestId("source-badge")).toHaveTextContent("ยืม");
  });

  it("renders nothing for pool, absent or unknown sources", () => {
    const { container, rerender } = render(<SourceBadge source="pool" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<SourceBadge source={undefined} />);
    expect(container).toBeEmptyDOMElement();
    expect(sourceBadgeLabel(null)).toBeNull();
  });
});
