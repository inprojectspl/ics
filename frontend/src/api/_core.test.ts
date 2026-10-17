import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, req } from "./_core";

function respond(status: number, body: string, statusText = "") {
  return vi.fn().mockResolvedValue(new Response(status === 204 ? null : body, { status, statusText }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("req", () => {
  it("resolves a 204 DELETE without parsing a body", async () => {
    const fetchMock = respond(204, "");
    vi.stubGlobal("fetch", fetchMock);
    await expect(req<void>("/api/assets/a1", { method: "DELETE" })).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assets/a1",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
    );
  });

  it("throws ApiError with the status, detail and code on 403", async () => {
    const body = JSON.stringify({ detail: "admin required", code: "admin_required" });
    vi.stubGlobal("fetch", respond(403, body, "Forbidden"));
    const err = await req("/api/admin/users/u1", { method: "DELETE" }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(403);
    expect((err as ApiError).detail).toBe("admin required");
    expect((err as ApiError).code).toBe("admin_required");
  });

  it("keeps the field the error is about", async () => {
    const body = JSON.stringify({ detail: "language: bad", code: "metadata_invalid", field: "language" });
    vi.stubGlobal("fetch", respond(400, body, "Bad Request"));
    const err = (await req("/api/assets/a1/meta").catch((e: unknown) => e)) as ApiError;
    expect(err.field).toBe("language");
  });

  it("leaves code null when the body has none", async () => {
    vi.stubGlobal("fetch", respond(502, "<html>bad gateway</html>", "Bad Gateway"));
    const err = (await req("/api/x").catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBeNull();
    expect(err.message).toBe("502 Bad Gateway");
  });

  it("still parses JSON bodies", async () => {
    vi.stubGlobal("fetch", respond(200, JSON.stringify({ deleted: true })));
    await expect(req<{ deleted: boolean }>("/api/x")).resolves.toEqual({ deleted: true });
  });
});
