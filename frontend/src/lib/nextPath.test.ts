import { afterEach, describe, expect, it } from "vitest";
import { currentNextPath, safeNextPath } from "./nextPath";

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

describe("currentNextPath", () => {
  afterEach(() => window.history.replaceState({}, "", "/"));

  it("is the page shown, with its query", () => {
    window.history.replaceState({}, "", "/projects/abc?tab=members#top");
    expect(currentNextPath()).toBe("/projects/abc?tab=members");
  });

  it("is nothing on the home page", () => {
    window.history.replaceState({}, "", "/#login");
    expect(currentNextPath()).toBeUndefined();
  });
});
