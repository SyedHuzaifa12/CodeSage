import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest, ApiError } from "@/lib/api/client";

function mockFetchOnce(body: unknown, init: { ok?: boolean; status?: number } = {}) {
  const ok = init.ok ?? true;
  const status = init.status ?? (ok ? 200 : 500);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status,
      json: () => Promise.resolve(body),
    }),
  );
}

describe("apiRequest — envelope handling", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("unwraps a successful {success,message,data} envelope to just `data`", async () => {
    mockFetchOnce({ success: true, message: "ok", data: { id: "abc" } });
    const data = await apiRequest<{ id: string }>("/repositories/abc");
    expect(data).toEqual({ id: "abc" });
  });

  it("throws ApiError with the backend's message/errors for a {success:false} envelope", async () => {
    mockFetchOnce(
      { success: false, message: "Repository not found.", errors: [{ detail: "not found" }] },
      { ok: false, status: 404 },
    );
    await expect(apiRequest("/repositories/missing")).rejects.toMatchObject({
      name: "ApiError",
      message: "Repository not found.",
      status: 404,
      errors: [{ detail: "not found" }],
    });
  });

  it("throws a network-kind ApiError when fetch itself rejects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    const err = await apiRequest("/repositories").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).kind).toBe("network");
  });

  it("throws a timeout-kind ApiError when the request is aborted", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => {
        const err = new Error("aborted");
        err.name = "AbortError";
        return Promise.reject(err);
      }),
    );
    const err = await apiRequest("/repositories").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).kind).toBe("timeout");
  });
});
