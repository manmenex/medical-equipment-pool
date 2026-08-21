import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";
import {
  LEGACY_TRANSACTION_HISTORY_DATASET_TYPE,
  confirmLegacyHistoryDryRunPlan,
  createLegacyHistorySession,
  dryRunLegacyHistorySession,
  executeLegacyHistorySession,
  getLegacyHistoryDryRunPlan,
  getLegacyHistorySession,
  listLegacyHistoryDryRunPlanRows,
  listLegacyHistorySessions,
  listLegacyHistoryValidationFindings,
  recoverLegacyHistorySession,
  uploadLegacyHistorySource,
  validateLegacyHistorySession,
} from "@/services/legacyHistoryImportClient";

// Roadmap PR21E: exact request-shape contract tests -- every call this
// client makes to the real, merged PR19/PR20/PR21E0 backend routes,
// asserting no extra client-derived business field (row set,
// expected_version, plan id invented locally, idempotency key, computed
// checksum) is ever sent, and that the dataset_type is exactly
// "legacy_transaction_history" -- never a reuse of the retired
// receive_history/issue_history mock category values.

afterEach(() => {
  vi.restoreAllMocks();
});

describe("legacyHistoryImportClient", () => {
  it("creates a session with exactly the legacy_transaction_history dataset_type, no other field", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "session-1" } });

    await createLegacyHistorySession();

    expect(postSpy).toHaveBeenCalledWith("/import-sessions", { dataset_type: LEGACY_TRANSACTION_HISTORY_DATASET_TYPE });
    expect(LEGACY_TRANSACTION_HISTORY_DATASET_TYPE).toBe("legacy_transaction_history");
  });

  it("lists sessions scoped to dataset_type=legacy_transaction_history with the given cursor/limit", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await listLegacyHistorySessions({ limit: 10, cursor: "abc" });

    expect(getSpy).toHaveBeenCalledWith("/import-sessions", {
      params: { dataset_type: "legacy_transaction_history", limit: 10, cursor: "abc" },
    });
  });

  it("fetches a single session by exact id through the shared generic route", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { id: "session-1" } });

    await getLegacyHistorySession("session-1");

    expect(getSpy).toHaveBeenCalledWith("/import-sessions/session-1");
  });

  it("uploads a source as multipart form data with only file (+ optional source_version), never a client-computed checksum", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "source-1", checksum: "a".repeat(64) } });
    const file = new File(["x"], "legacy-history.xlsx");

    await uploadLegacyHistorySource("session-1", file, "v2");

    expect(postSpy).toHaveBeenCalledTimes(1);
    const [url, body, config] = postSpy.mock.calls[0] as [string, FormData, { headers: Record<string, string> }];
    expect(url).toBe("/import-sessions/session-1/source/upload");
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("file")).toBe(file);
    expect(body.get("source_version")).toBe("v2");
    expect(body.has("checksum")).toBe(false);
    expect(config.headers["Content-Type"]).toBe("multipart/form-data");
  });

  it("omits source_version from the form when not provided", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "source-1" } });
    const file = new File(["x"], "legacy-history.xlsx");

    await uploadLegacyHistorySource("session-1", file);

    const [, body] = postSpy.mock.calls[0] as [string, FormData];
    expect(body.has("source_version")).toBe(false);
  });

  it("triggers validate as a bodyless POST", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "session-1", status: "validating" } });

    await validateLegacyHistorySession("session-1");

    expect(postSpy).toHaveBeenCalledWith("/import-sessions/session-1/validate");
    expect(postSpy.mock.calls[0]).toHaveLength(1);
  });

  it("triggers dry-run as a bodyless POST", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "session-1", status: "dry_run_running" } });

    await dryRunLegacyHistorySession("session-1");

    expect(postSpy).toHaveBeenCalledWith("/import-sessions/session-1/dry-run");
    expect(postSpy.mock.calls[0]).toHaveLength(1);
  });

  it("executes as a bodyless POST -- never a row set, expected_version, or idempotency key", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "session-1", status: "executing" } });

    await executeLegacyHistorySession("session-1");

    expect(postSpy).toHaveBeenCalledWith("/import-sessions/session-1/execute");
    expect(postSpy.mock.calls[0]).toHaveLength(1);
  });

  it("recovers as a bodyless POST", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "session-1", status: "created" } });

    await recoverLegacyHistorySession("session-1");

    expect(postSpy).toHaveBeenCalledWith("/import-sessions/session-1/recover");
    expect(postSpy.mock.calls[0]).toHaveLength(1);
  });

  it("lists validation findings with only limit/cursor/attempt_id", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await listLegacyHistoryValidationFindings("session-1", { limit: 25, cursor: null, attempt_id: "attempt-1" });

    expect(getSpy).toHaveBeenCalledWith("/import-sessions/session-1/errors", {
      params: { limit: 25, cursor: null, attempt_id: "attempt-1" },
    });
  });

  it("fetches the PR21 dry-run plan identity/summary with no query params and no client-supplied plan id", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { id: "plan-1" } });

    await getLegacyHistoryDryRunPlan("session-1");

    expect(getSpy).toHaveBeenCalledWith("/import-sessions/session-1/legacy-history/dry-run-plan");
  });

  it("lists plan rows scoped to the exact session id and plan id, with only limit/cursor", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await listLegacyHistoryDryRunPlanRows("session-1", "plan-1", { limit: 25, cursor: "next" });

    expect(getSpy).toHaveBeenCalledWith("/import-sessions/session-1/legacy-history/dry-run-plan/plan-1/rows", {
      params: { limit: 25, cursor: "next" },
    });
  });

  it("confirms using the exact plan id passed in, in the URL path, bodyless", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "plan-1", confirmed_at: "now" } });

    await confirmLegacyHistoryDryRunPlan("session-1", "plan-1");

    expect(postSpy).toHaveBeenCalledWith("/import-sessions/session-1/legacy-history/dry-run-plan/plan-1/confirm");
    expect(postSpy.mock.calls[0]).toHaveLength(1);
  });
});
