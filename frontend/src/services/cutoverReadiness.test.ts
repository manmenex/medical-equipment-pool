import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";
import {
  createCutoverDecision,
  cutoverReadinessKeys,
  fetchCutoverDecision,
  fetchCutoverGateEvaluation,
  fetchCutoverReadinessRun,
  fetchCutoverReadinessRuns,
} from "@/services/cutoverReadiness";

// Roadmap PR23E -- exact request-shape contract tests for every call this
// client makes to the already-merged PR23B/C/D backend routes. Asserts no
// client-derived business field (a computed readiness/eligibility value,
// a guessed/incremented version, a client-supplied actor id) is ever
// sent -- the frontend is a thin, honest wrapper only.

afterEach(() => {
  vi.restoreAllMocks();
});

describe("cutoverReadiness service", () => {
  it("lists runs with the given cursor/limit, no extra params", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await fetchCutoverReadinessRuns({ limit: 25, cursor: "abc" });

    expect(getSpy).toHaveBeenCalledWith("/cutover-readiness-runs", { params: { limit: 25, cursor: "abc" } });
  });

  it("fetches a single run by id", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: {} });

    await fetchCutoverReadinessRun("run-1");

    expect(getSpy).toHaveBeenCalledWith("/cutover-readiness-runs/run-1");
  });

  it("fetches the gate evaluation for a run at exactly the documented route", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: {} });

    await fetchCutoverGateEvaluation("run-1");

    expect(getSpy).toHaveBeenCalledWith("/cutover-readiness-runs/run-1/gate-evaluation");
  });

  it("fetches the decision for a run at exactly the documented route", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: {} });

    await fetchCutoverDecision("run-1");

    expect(getSpy).toHaveBeenCalledWith("/cutover-readiness-runs/run-1/decision");
  });

  it("submits a decision with exactly the four DecisionCreateRequest fields, never a client-computed readiness field", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: {} });

    await createCutoverDecision("run-1", {
      expected_version: 5,
      decision: "GO",
      acknowledged_warning_codes: ["GATE_F_STAFF_TRAINING_NOT_AUTOMATED"],
      no_go_reason: undefined,
    });

    expect(postSpy).toHaveBeenCalledWith("/cutover-readiness-runs/run-1/decision", {
      expected_version: 5,
      decision: "GO",
      acknowledged_warning_codes: ["GATE_F_STAFF_TRAINING_NOT_AUTOMATED"],
      no_go_reason: undefined,
    });
    const [, body] = postSpy.mock.calls[0];
    expect(Object.keys(body as object).sort()).toEqual(
      ["acknowledged_warning_codes", "decision", "expected_version", "no_go_reason"].sort()
    );
  });
});

describe("cutoverReadinessKeys", () => {
  it("produces distinct, stable keys per resource", () => {
    expect(cutoverReadinessKeys.run("run-1")).toEqual(["cutoverReadiness", "run", "run-1"]);
    expect(cutoverReadinessKeys.gates("run-1")).toEqual(["cutoverReadiness", "run", "run-1", "gates"]);
    expect(cutoverReadinessKeys.decision("run-1")).toEqual(["cutoverReadiness", "run", "run-1", "decision"]);
  });
});
