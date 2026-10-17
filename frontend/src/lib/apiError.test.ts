import { describe, it, expect } from "vitest";
import { ApiError } from "../api/_core";
import { formatApiError, statusCode } from "./apiError";

describe("formatApiError", () => {
  it("maps 401 to the sign-in message", () => {
    expect(formatApiError(new Error("401 Unauthorized"))).toBe(
      "You need to sign in.",
    );
  });

  it("maps 403 to not allowed", () => {
    expect(formatApiError(new Error("403 Forbidden"))).toBe(
      "You are not allowed to do this.",
    );
  });

  it("maps 404 to not found", () => {
    expect(formatApiError(new Error("404 Not Found"))).toContain("Not found");
  });

  it("maps 409 to conflict", () => {
    expect(formatApiError(new Error("409 Conflict"))).toContain("Conflict");
  });

  it("maps 410 to no longer available", () => {
    expect(formatApiError(new Error("410 Gone"))).toContain("No longer available");
  });

  it("maps 413 to file too large", () => {
    expect(formatApiError(new Error("413 Payload Too Large"))).toContain(
      "too large",
    );
  });

  it("maps 429 to rate limiting", () => {
    expect(formatApiError(new Error("429 Too Many"))).toContain("Too many attempts");
  });

  it("maps 5xx to server error", () => {
    expect(formatApiError(new Error("500 Server Error"))).toContain(
      "Server error",
    );
    expect(formatApiError(new Error("503 Service Unavailable"))).toContain(
      "Server error",
    );
  });

  it("returns the fallback for an unknown error", () => {
    expect(formatApiError(new Error("418 I'm a teapot"), "default")).toBe(
      "default",
    );
  });

  it("uses the original message without a fallback", () => {
    expect(formatApiError(new Error("something random"))).toBe("something random");
  });

  it("handles a non-Error (string)", () => {
    expect(formatApiError("401 raw")).toBe("You need to sign in.");
  });
});

describe("formatApiError with error codes", () => {
  it("picks the message by code, not by detail", () => {
    const err = new ApiError(409, "cdn.x.io is already on the list", "cdn.x.io is already on the list", "cdn_host_exists");
    expect(formatApiError(err)).toBe("This host is already on the list.");
  });

  it("maps a generic code to the status copy", () => {
    expect(formatApiError(new ApiError(404, "Not Found", "Not Found", "not_found"))).toContain(
      "Not found",
    );
  });

  it("uses the status copy for an unknown code and never shows detail", () => {
    expect(formatApiError(new ApiError(400, "odd failure", "odd failure", "brand_new_code"))).toBe(
      "Invalid data. Check the form.",
    );
  });

  it("lets the caller's fallback beat the status copy when the server explained", () => {
    expect(formatApiError(new ApiError(400, "odd failure", "odd failure"), "Could not do it")).toBe(
      "Could not do it",
    );
  });
});

describe("statusCode", () => {
  it("reads the code from the start of the message", () => {
    expect(statusCode(new Error("404 Not Found"))).toBe(404);
    expect(statusCode(new Error("500"))).toBe(500);
  });

  it("returns null without a code", () => {
    expect(statusCode(new Error("network down"))).toBeNull();
  });

  it("returns null when it is not a number", () => {
    expect(statusCode(new Error("BAD bad bad"))).toBeNull();
  });

  it("reads the status from ApiError when the message has none", () => {
    // FastAPI returns its own `detail`, so the error message is prose without
    // digits; a regex alone would miss the status.
    expect(statusCode(new ApiError(401, "You must be signed in", "You must be signed in"))).toBe(
      401,
    );
    expect(statusCode(new ApiError(404, null, "404 Not Found"))).toBe(404);
  });
});
