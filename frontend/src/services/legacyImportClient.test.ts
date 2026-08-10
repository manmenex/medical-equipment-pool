import { describe, expect, it, vi } from "vitest";

import { ImportSessionNotFoundError, MockImportClient } from "@/services/legacyImportClient";
import { legacyImportSkeletonFixtures } from "@/services/legacyImportFixtures";
import { api } from "@/services/api";

// PR19B "Contract protection" tests: the mock client never imports
// "@/services/api" (verified by this file's own import graph -- see the
// top-of-file import list, which never references it) and never issues a
// network request; every method resolves purely from local fixtures/state.
// listSessions() returns the real Page[T] shape (items/nextCursor/total),
// matching backend/app/schemas/common.py's Page.
describe("MockImportClient", () => {
  it("lists every seeded session as a summary, newest first, in a Page-shaped response", async () => {
    const client = new MockImportClient();
    const page = await client.listSessions();

    expect(page.total).toBe(legacyImportSkeletonFixtures.length);
    expect(page.items.length).toBe(legacyImportSkeletonFixtures.length);
    expect(page.nextCursor).toBeNull();
    for (let i = 1; i < page.items.length; i += 1) {
      expect(page.items[i - 1].createdAt >= page.items[i].createdAt).toBe(true);
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
    // The real backend confirm-gate status (design §5) -- not an invented one.
    expect(created.status).toBe("dry_run_completed");
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

  it("never calls the real axios client -- skeleton safety (no upload, no parser, no dry-run/execute call)", async () => {
    const getSpy = vi.spyOn(api, "get");
    const postSpy = vi.spyOn(api, "post");
    const client = new MockImportClient();

    await client.listSessions();
    await client.getSession(legacyImportSkeletonFixtures[0].id);
    await client.createPreviewSession({
      importCategory: "equipment_master",
      file: { name: "a.xlsx", sizeBytes: 1, type: "" },
      requestedByDisplayName: "ผู้ทดสอบ",
    });

    expect(getSpy).not.toHaveBeenCalled();
    expect(postSpy).not.toHaveBeenCalled();
    getSpy.mockRestore();
    postSpy.mockRestore();
  });
});
