import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";
import {
  EQUIPMENT_MASTER_DATASET_TYPE,
  confirmEquipmentMasterDryRunPlan,
  createEquipmentMasterSession,
  dryRunEquipmentMasterSession,
  executeEquipmentMasterSession,
  getEquipmentMasterDryRunPlan,
  getEquipmentMasterSession,
  listEquipmentMasterSessions,
  listEquipmentMasterValidationFindings,
  recoverEquipmentMasterSession,
  uploadEquipmentMasterSource,
  validateEquipmentMasterSession,
} from "@/services/equipmentMasterImportClient";

// Roadmap PR20F design §41: exact request-shape contract tests -- every
// call this client makes to the real, merged PR20A-E backend routes
// (backend/app/api/v1/import_sessions.py), asserting no extra
// client-derived business field (row set, expected_version, plan id
// invented locally, idempotency key, computed checksum) is ever sent.

afterEach(() => {
  vi.restoreAllMocks();
});

describe("equipmentMasterImportClient", () => {
  it("creates a session with exactly the equipment_master dataset_type, no other field", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "session-1" } });

    await createEquipmentMasterSession();

    expect(postSpy).toHaveBeenCalledWith("/import-sessions", { dataset_type: EQUIPMENT_MASTER_DATASET_TYPE });
    expect(EQUIPMENT_MASTER_DATASET_TYPE).toBe("equipment_master");
  });

  it("lists sessions scoped to dataset_type=equipment_master with the given cursor/limit", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await listEquipmentMasterSessions({ limit: 10, cursor: "abc" });

    expect(getSpy).toHaveBeenCalledWith("/import-sessions", {
      params: { dataset_type: "equipment_master", limit: 10, cursor: "abc" },
    });
  });

  it("fetches a single session by exact id, no query params", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { id: "session-1" } });

    await getEquipmentMasterSession("session-1");

    expect(getSpy).toHaveBeenCalledWith("/import-sessions/session-1");
  });

  it("uploads a source as multipart form data with only file (+ optional source_version), never a client-computed checksum", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "source-1" } });
    const file = new File(["x"], "equipment.xlsx");

    await uploadEquipmentMasterSource("session-1", file, "v2");

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
    const file = new File(["x"], "equipment.xlsx");

    await uploadEquipmentMasterSource("session-1", file);

    const [, body] = postSpy.mock.calls[0] as [string, FormData];
    expect(body.has("source_version")).toBe(false);
  });

  it("triggers validate as a bodyless POST", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "session-1", status: "validating" } });

    await validateEquipmentMasterSession("session-1");

    expect(postSpy).toHaveBeenCalledWith("/import-sessions/session-1/validate");
    expect(postSpy.mock.calls[0]).toHaveLength(1);
  });

  it("triggers dry-run as a bodyless POST", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "session-1", status: "dry_run_running" } });

    await dryRunEquipmentMasterSession("session-1");

    expect(postSpy).toHaveBeenCalledWith("/import-sessions/session-1/dry-run");
    expect(postSpy.mock.calls[0]).toHaveLength(1);
  });

  it("executes as a bodyless POST -- never a row set, expected_version, or idempotency key", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "session-1", status: "executing" } });

    await executeEquipmentMasterSession("session-1");

    expect(postSpy).toHaveBeenCalledWith("/import-sessions/session-1/execute");
    expect(postSpy.mock.calls[0]).toHaveLength(1);
  });

  it("recovers as a bodyless POST", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "session-1", status: "created" } });

    await recoverEquipmentMasterSession("session-1");

    expect(postSpy).toHaveBeenCalledWith("/import-sessions/session-1/recover");
    expect(postSpy.mock.calls[0]).toHaveLength(1);
  });

  it("fetches the dry-run plan with only limit/cursor -- never a client-supplied plan id", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { id: "plan-1", rows: [] } });

    await getEquipmentMasterDryRunPlan("session-1", { limit: 25, cursor: "next" });

    expect(getSpy).toHaveBeenCalledWith("/import-sessions/session-1/dry-run-plan", {
      params: { limit: 25, cursor: "next" },
    });
  });

  it("confirms using the exact plan id passed in, in the URL path, bodyless", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ data: { id: "plan-1", confirmed_at: "now" } });

    await confirmEquipmentMasterDryRunPlan("session-1", "plan-1");

    expect(postSpy).toHaveBeenCalledWith("/import-sessions/session-1/dry-run-plan/plan-1/confirm");
    expect(postSpy.mock.calls[0]).toHaveLength(1);
  });

  it("lists validation findings with only limit/cursor/attempt_id", async () => {
    const getSpy = vi.spyOn(api, "get").mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });

    await listEquipmentMasterValidationFindings("session-1", { limit: 25, cursor: null, attempt_id: "attempt-1" });

    expect(getSpy).toHaveBeenCalledWith("/import-sessions/session-1/errors", {
      params: { limit: 25, cursor: null, attempt_id: "attempt-1" },
    });
  });
});
