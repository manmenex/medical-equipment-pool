import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";
import { createReturn } from "@/services/borrow";

// Roadmap PR8B (knowledge/adr/ADR-006-receipt-outcome-contract.md,
// backend/app/schemas/transaction.py's ReturnRequest): receipt_outcome
// replaces condition entirely, no compatibility alias. This proves the
// frontend's request payload matches the current backend contract exactly
// -- a regression here (e.g. someone reintroducing `condition`) would make
// every receipt submission fail with 422 against the current backend.

// Codex review round 1 (GitHub PR #29): restore in afterEach, not at the
// end of each test body -- a failed assertion before the per-test
// mockRestore() call would otherwise leave api.post spied/mocked for
// every subsequent test in this file.
afterEach(() => {
  vi.restoreAllMocks();
});

describe("createReturn", () => {
  it("submits receipt_outcome, never the retired condition field", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({
      data: { id: "tx-1", status: "closed" },
    });

    await createReturn("tx-1", { receipt_outcome: "usable", notes: "all good" });

    expect(postSpy).toHaveBeenCalledWith("/return/tx-1", {
      receipt_outcome: "usable",
      notes: "all good",
    });
    const [, payload] = postSpy.mock.calls[0] as [string, Record<string, unknown>];
    expect(payload).not.toHaveProperty("condition");
  });

  it("submits the defective outcome unchanged", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "tx-2", status: "closed" } });

    await createReturn("tx-2", { receipt_outcome: "defective" });

    expect(postSpy).toHaveBeenCalledWith("/return/tx-2", { receipt_outcome: "defective" });
  });
});
