import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";
import {
  createReconciliationSignoff,
  fetchReconciliationFinding,
  fetchReconciliationFindings,
  fetchReconciliationRun,
  fetchReconciliationRuns,
  fetchReconciliationSignoff,
  reconciliationKeys,
  updateReconciliationFindingDisposition,
} from "@/services/reconciliation";

// Roadmap PR22F §39 of the task -- exact request-shape contract tests
// for every call this client makes to the already-merged PR22D/PR22E
// backend routes. Asserts no client-derived business field (attestation,
// finding counts, coverage values, signer id, a guessed/incremented
// version) is ever sent -- the frontend is a thin, honest wrapper only.

afterEach(() => {
  vi.restoreAllMocks();
});

describe("reconciliation service", () => {
  it("lists runs with the given cursor/limit, no extra params", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await fetchReconciliationRuns({ limit: 25, cursor: "abc" });

    expect(getSpy).toHaveBeenCalledWith("/legacy-reconciliation-runs", { params: { limit: 25, cursor: "abc" } });
  });

  it("fetches a single run by id", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: {} });

    await fetchReconciliationRun("run-1");

    expect(getSpy).toHaveBeenCalledWith("/legacy-reconciliation-runs/run-1");
  });

  it("lists findings for a run with exactly the given filters, never client-side re-filtered", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await fetchReconciliationFindings("run-1", {
      limit: 25,
      cursor: null,
      code: "DUPLICATE_EXACT",
      severity: "high",
      disposition: "open",
    });

    expect(getSpy).toHaveBeenCalledWith("/legacy-reconciliation-runs/run-1/findings", {
      params: { limit: 25, cursor: null, code: "DUPLICATE_EXACT", severity: "high", disposition: "open" },
    });
  });

  it("fetches a single finding by id", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: {} });

    await fetchReconciliationFinding("finding-1");

    expect(getSpy).toHaveBeenCalledWith("/legacy-reconciliation-findings/finding-1");
  });

  it("submits disposition with exactly disposition/expected_version/disposition_note -- the finding's own currently-loaded version, never guessed", async () => {
    const patchSpy = vi.spyOn(api, "patch").mockResolvedValue({ data: {} });

    await updateReconciliationFindingDisposition("finding-1", {
      disposition: "confirmed_valid",
      expected_version: 3,
      disposition_note: "note",
    });

    expect(patchSpy).toHaveBeenCalledWith("/legacy-reconciliation-findings/finding-1/disposition", {
      disposition: "confirmed_valid",
      expected_version: 3,
      disposition_note: "note",
    });
  });

  it("fetches the sign-off for a run", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: {} });

    await fetchReconciliationSignoff("run-1");

    expect(getSpy).toHaveBeenCalledWith("/legacy-reconciliation-runs/run-1/sign-off");
  });

  it("submits sign-off with ONLY expected_version -- never a client-constructed attestation, finding counts, coverage values, or signer id", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: {} });

    await createReconciliationSignoff("run-1", { expected_version: 4 });

    expect(postSpy).toHaveBeenCalledWith("/legacy-reconciliation-runs/run-1/sign-off", { expected_version: 4 });
    const [, body] = postSpy.mock.calls[0];
    expect(Object.keys(body as object)).toEqual(["expected_version"]);
  });
});

describe("reconciliationKeys", () => {
  it("produces distinct, stable keys per resource", () => {
    expect(reconciliationKeys.run("run-1")).toEqual(["reconciliation", "run", "run-1"]);
    expect(reconciliationKeys.signoff("run-1")).toEqual(["reconciliation", "run", "run-1", "signoff"]);
    expect(reconciliationKeys.finding("finding-1")).toEqual(["reconciliation", "finding", "finding-1"]);
  });
});
