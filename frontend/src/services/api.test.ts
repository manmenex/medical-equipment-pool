import axios, { type AxiosAdapter } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "@/lib/queryClient";
import { api, resetRefreshState } from "@/services/api";
import { isMarkedOffline, isUnreachableError, setMarkedOffline } from "@/services/connectivity";
import { useAuthStore } from "@/store/authStore";

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

  it("does not navigate when already on the change-password page", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/change-password", assign });
    const adapter: AxiosAdapter = (config) =>
      Promise.reject({
        isAxiosError: true,
        config,
        response: { status: 403, data: { code: "PASSWORD_CHANGE_REQUIRED" }, config },
      });

    await expect(api.get("/equipment", { adapter })).rejects.toBeTruthy();
    expect(assign).not.toHaveBeenCalled();
  });
});

describe("api refresh handling (PR25E S1)", () => {
  function expired(): AxiosAdapter {
    return (config) =>
      Promise.reject({ isAxiosError: true, config, response: { status: 401, data: {}, config, headers: {} } });
  }

  beforeEach(() => {
    resetRefreshState();
    setMarkedOffline(false);
    useAuthStore.setState({ accessToken: "old", user: { id: "u1" } as never });
  });
  afterEach(() => vi.restoreAllMocks());

  it("keeps the session and marks offline when refresh hits a network error", async () => {
    vi.spyOn(axios, "post").mockRejectedValue(Object.assign(new Error("Network Error"), { isAxiosError: true }));
    await expect(api.get("/equipment", { adapter: expired() })).rejects.toBeTruthy();
    expect(useAuthStore.getState().accessToken).toBe("old");
    expect(useAuthStore.getState().user).not.toBeNull();
    expect(isMarkedOffline()).toBe(true);
  });

  it("keeps the session on a 503 from refresh and backs off", async () => {
    const post = vi.spyOn(axios, "post").mockRejectedValue({
      isAxiosError: true,
      response: { status: 503, data: {}, headers: {} },
    });
    await expect(api.get("/a", { adapter: expired() })).rejects.toBeTruthy();
    await expect(api.get("/b", { adapter: expired() })).rejects.toBeTruthy();
    expect(post).toHaveBeenCalledTimes(1); // second call inside backoff window
    expect(useAuthStore.getState().accessToken).toBe("old");
  });

  it("logs out when refresh returns 401", async () => {
    vi.spyOn(axios, "post").mockRejectedValue({
      isAxiosError: true,
      response: { status: 401, data: {}, headers: {} },
    });
    await expect(api.get("/equipment", { adapter: expired() })).rejects.toBeTruthy();
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("logs out when refresh reports ACCOUNT_LOCKED", async () => {
    vi.spyOn(axios, "post").mockRejectedValue({
      isAxiosError: true,
      response: { status: 423, data: { code: "ACCOUNT_LOCKED" }, headers: {} },
    });
    await expect(api.get("/equipment", { adapter: expired() })).rejects.toBeTruthy();
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("does not log out on PASSWORD_CHANGE_REQUIRED from refresh", async () => {
    vi.spyOn(axios, "post").mockRejectedValue({
      isAxiosError: true,
      response: { status: 403, data: { code: "PASSWORD_CHANGE_REQUIRED" }, headers: {} },
    });
    await expect(api.get("/equipment", { adapter: expired() })).rejects.toBeTruthy();
    expect(useAuthStore.getState().accessToken).toBe("old");
  });

  it("shares one refresh across concurrent requests and retries them", async () => {
    let resolveRefresh!: (v: unknown) => void;
    const post = vi.spyOn(axios, "post").mockReturnValue(
      new Promise((r) => {
        resolveRefresh = r;
      }) as never
    );
    const adapter: AxiosAdapter = (config) => {
      if (config.headers.Authorization === "Bearer new") {
        return Promise.resolve({ data: "ok", status: 200, statusText: "OK", headers: {}, config });
      }
      return Promise.reject({ isAxiosError: true, config, response: { status: 401, data: {}, config, headers: {} } });
    };
    const calls = [api.get("/a", { adapter }), api.get("/b", { adapter }), api.get("/c", { adapter })];
    await new Promise((r) => setTimeout(r, 0));
    resolveRefresh({ data: { access_token: "new" } });
    const results = await Promise.all(calls);
    expect(results.map((r) => r.data)).toEqual(["ok", "ok", "ok"]);
    expect(post).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().accessToken).toBe("new");
  });
});

describe("isUnreachableError", () => {
  it("classifies network, gateway and html responses as unreachable, auth as not", () => {
    const e = (response?: object) => ({ isAxiosError: true, response });
    expect(isUnreachableError(e())).toBe(true);
    expect(isUnreachableError(e({ status: 502, headers: {} }))).toBe(true);
    expect(isUnreachableError(e({ status: 200, headers: { "content-type": "text/html" } }))).toBe(true);
    expect(isUnreachableError(e({ status: 401, headers: {} }))).toBe(false);
    expect(isUnreachableError(e({ status: 409, headers: {} }))).toBe(false);
    expect(isUnreachableError(new Error("x"))).toBe(false);
  });
});

describe("logout wipe", () => {
  it("clears the query cache", () => {
    queryClient.setQueryData(["x"], 1);
    useAuthStore.getState().logout();
    expect(queryClient.getQueryData(["x"])).toBeUndefined();
  });
});
