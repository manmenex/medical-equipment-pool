import type { AxiosAdapter } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/services/api";

describe("api PASSWORD_CHANGE_REQUIRED handling", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the user to the change-password page", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/equipment", assign });
    const adapter: AxiosAdapter = (config) =>
      Promise.reject({
        isAxiosError: true,
        config,
        response: { status: 403, data: { code: "PASSWORD_CHANGE_REQUIRED" }, config },
      });

    await expect(api.get("/equipment", { adapter })).rejects.toBeTruthy();
    expect(assign).toHaveBeenCalledWith("/change-password");
  });
});
