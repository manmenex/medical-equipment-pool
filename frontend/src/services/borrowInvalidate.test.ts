import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as helper from "@/lib/invalidateOperationalData";
import { OPERATIONAL_QUERY_KEYS } from "@/lib/invalidateOperationalData";
import { api } from "@/services/api";
import {
  addHn,
  changeTransactionDevice,
  correctTransactionWard,
  createBorrow,
  createReturn,
  dispatchBatch,
  receiptBatch,
  switchTransactionAction,
  undoTransaction,
  voidTransaction,
} from "@/services/borrow";

vi.mock("@/services/api", () => ({ api: { post: vi.fn(), get: vi.fn() } }));
vi.mock("@/lib/invalidateOperationalData", async (orig) => {
  const actual = await orig<typeof import("@/lib/invalidateOperationalData")>();
  return { ...actual, invalidateOperationalData: vi.fn(() => Promise.resolve([])) };
});

describe("mutation paths call invalidateOperationalData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue({ data: {} });
  });

  const cases: [string, () => Promise<unknown>][] = [
    ["createBorrow", () => createBorrow({} as never)],
    ["createReturn", () => createReturn("t1", {} as never)],
    ["dispatchBatch", () => dispatchBatch({} as never)],
    ["receiptBatch", () => receiptBatch({} as never)],
    ["addHn", () => addHn("t1", "123")],
    ["correctTransactionWard (ward correction)", () => correctTransactionWard("t1", {} as never)],
    ["undoTransaction", () => undoTransaction("t1")],
    ["voidTransaction", () => voidTransaction("t1", "r")],
    ["changeTransactionDevice", () => changeTransactionDevice("t1", { reason: "r", equipment_id: "e" })],
    ["switchTransactionAction", () => switchTransactionAction("t1", { reason: "r" })],
  ];

  it.each(cases)("%s", async (_n, run) => {
    await run();
    expect(helper.invalidateOperationalData).toHaveBeenCalledTimes(1);
  });

  it("does not invalidate when the request fails", async () => {
    (api.post as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("409"));
    await expect(undoTransaction("t1")).rejects.toThrow();
    expect(helper.invalidateOperationalData).not.toHaveBeenCalled();
  });
});

describe("invalidateOperationalData", () => {
  it("invalidates every operational key prefix", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const real = await vi.importActual<typeof import("@/lib/invalidateOperationalData")>("@/lib/invalidateOperationalData");
    await real.invalidateOperationalData(qc);
    const keys = spy.mock.calls.map((c) => (c[0]?.queryKey as string[])[0]);
    expect(keys).toEqual([...OPERATIONAL_QUERY_KEYS]);
    for (const k of ["equipment", "transactions", "active-borrows", "dashboard", "standby-summary", "reports"]) {
      expect(keys).toContain(k);
    }
  });
});
