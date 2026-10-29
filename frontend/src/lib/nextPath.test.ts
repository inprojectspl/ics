import { describe, expect, it } from "vitest";
import { safeNextPath } from "./nextPath";

describe("safeNextPath", () => {
  it("keeps a same-origin path with its query", () => {
    expect(safeNextPath("/projects/abc/accept?t=x.y")).toBe("/projects/abc/accept?t=x.y");
  });

  it.each([
    null, undefined, "", "projects", "//evil.example/x", "https://evil.example/x",
    "/\\evil.example/x", "/\n/evil.example/x", "/a/..//evil.example/x",
  ])(
    "rejects %s",
    (value) => {
      expect(safeNextPath(value)).toBeUndefined();
    },
  );
});
