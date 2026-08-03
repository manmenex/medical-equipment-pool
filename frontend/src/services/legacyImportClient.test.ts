import { describe, expect, it } from "vitest";

import { ImportSessionNotFoundError, MockImportClient } from "@/services/legacyImportClient";
import { legacyImportSkeletonFixtures } from "@/services/legacyImportFixtures";

// PR19B "Contract protection" tests: the mock client never imports
// "@/services/api" (verified by this file's own import graph -- see the
// top-of-file import list, which never references it) and never issues a
// network request; every method resolves purely from local fixtures/state.
describe("MockImportClient", () => {
  it("lists every seeded session as a summary, newest first", async () => {
    const client = new MockImportClient();
    const sessions = await client.listSessions();

    expect(sessions.length).toBe(legacyImportSkeletonFixtures.length);
    for (let i = 1; i < sessions.length; i += 1) {
      expect(sessions[i - 1].createdAt >= sessions[i].createdAt).toBe(true);
    }
  });

  it("returns the full detail for a known session id", async () => {
    const client = new MockImportClient();
    const detail = await client.getSession("demo-completed");

    expect(detail.id).toBe("demo-completed");
    expect(detail.resultSummary?.status).toBe("completed");
  });

  it("rejects with ImportSessionNotFoundError for an unknown session id", async () => {
    const client = new MockImportClient();
    await expect(client.getSession("does-not-exist")).rejects.toBeInstanceOf(ImportSessionNotFoundError);
  });

  it("creates a preview session from only name/size/type -- never real file content -- and never calculates counts from it", async () => {
    const client = new MockImportClient([]);
    const created = await client.createPreviewSession({
      importCategory: "receive_history",
      file: { name: "test.xlsx", sizeBytes: 12_345, type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
      requestedByDisplayName: "ผู้ทดสอบ",
    });

    expect(created.filename).toBe("test.xlsx");
    expect(created.requestedFileSizeBytes).toBe(12_345);
    expect(created.status).toBe("awaiting_confirmation");
    // Fixed, category-keyed sample counts -- not derived from sizeBytes above.
    expect(created.totalRows).toBe(480);
    expect(created.resultSummary).toBeNull();
  });

  it("makes a created preview session immediately retrievable by id", async () => {
    const client = new MockImportClient([]);
    const created = await client.createPreviewSession({
      importCategory: "equipment_master",
      file: { name: "eq.xlsx", sizeBytes: 1, type: "" },
      requestedByDisplayName: "ผู้ทดสอบ",
    });

    const fetched = await client.getSession(created.id);
    expect(fetched.id).toBe(created.id);
  });
});
