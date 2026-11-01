import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/services/api", () => ({ api: { get: (...a: unknown[]) => get(...a), post: vi.fn() } }));

import { fetchSnapshotPage } from "./syncClient";

beforeEach(() => get.mockReset());

describe("fetchSnapshotPage", () => {
  it("sends If-None-Match and treats HTTP 304 as not modified", async () => {
    get.mockResolvedValue({ status: 304, data: "", headers: {} });
    const res = await fetchSnapshotPage("wards", { etag: '"abc"', cursor: "c" });
    expect(res).toEqual({ notModified: true });
    const [url, cfg] = get.mock.calls[0];
    expect(url).toBe("/sync/snapshot");
    expect(cfg.headers).toEqual({ "If-None-Match": '"abc"' });
    expect(cfg.params).toEqual({ section: "wards", cursor: "c", limit: 200 });
    expect(cfg.validateStatus(304)).toBe(true);
    expect(cfg.validateStatus(500)).toBe(false);
  });

  it("returns the page and prefers the ETag header over the body", async () => {
    const data = { section: "wards", items: [{ id: "w" }], next_cursor: null, etag: '"body"', server_time: "t" };
    get.mockResolvedValue({ status: 200, data, headers: { etag: '"hdr"' } });
    const res = await fetchSnapshotPage("wards");
    expect(res).toEqual({ notModified: false, page: data, etag: '"hdr"' });
    expect(get.mock.calls[0][1].headers).toBeUndefined();
  });
});
