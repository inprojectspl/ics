/**
 * Tests for the api.ts helpers (`req`, `encodePath`, `postJson`).
 *
 * The api object itself wraps individual backend endpoints, which have low
 * ROI per test line and are covered by per-module tests. Here we cover the
 * shared helpers that hold the error mapping and path encoding policy.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { encodePath, postJson, req } from "./api";
import { setLocale } from "./lib/i18n";

describe("encodePath", () => {
  it("encodes special characters in segments", () => {
    expect(encodePath("foo bar/baz")).toBe("foo%20bar/baz");
  });

  it("keeps the `/` separators", () => {
    expect(encodePath("a/b/c")).toBe("a/b/c");
  });

  it("escapes non-ASCII characters", () => {
    expect(encodePath("café/naïve")).toBe(
      "caf%C3%A9/na%C3%AFve",
    );
  });

  it("encodes URL-reserved characters", () => {
    expect(encodePath("path?with#hash")).toBe("path%3Fwith%23hash");
  });

  it("returns an empty string for an empty segment", () => {
    expect(encodePath("")).toBe("");
  });
});

describe("req", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns JSON for 2xx", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ hello: "world" }),
    });
    const data = await req<{ hello: string }>("/api/x");
    expect(data).toEqual({ hello: "world" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("always sends `credentials: include` (session cookie)", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    await req("/api/x");
    const [, init] = fetchMock.mock.calls[0]!;
    expect(init.credentials).toBe("include");
  });

  it("throws an Error with `detail` from the backend JSON", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 413,
      statusText: "Payload Too Large",
      json: async () => ({ detail: "asset too large" }),
    });
    await expect(req("/api/x")).rejects.toThrow("asset too large");
  });

  it("falls back to `<status> <statusText>` when the body is not JSON", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => {
        throw new Error("not json");
      },
    });
    await expect(req("/api/x")).rejects.toThrow("500 Internal Server Error");
  });

  it("merges custom headers", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    await req("/api/x", { headers: { "X-Test": "y" } });
    const [, init] = fetchMock.mock.calls[0]!;
    expect(init.headers["X-Test"]).toBe("y");
  });

  it("sends the UI locale as Accept-Language", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
    await req("/api/x");
    expect(fetchMock.mock.calls[0]![1].headers["Accept-Language"]).toBe("en");
    setLocale("pl", { persist: false });
    await req("/api/x");
    expect(fetchMock.mock.calls[1]![1].headers["Accept-Language"]).toBe("pl");
  });
});

describe("postJson", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends a POST with a JSON body", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) });
    await postJson("/api/foo", { name: "bar" });
    const [, init] = fetchMock.mock.calls[0]!;
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ name: "bar" });
  });
});
