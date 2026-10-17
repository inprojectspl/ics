import { describe, it, expect, vi, beforeEach } from "vitest";
import { navigate } from "./navigate";

describe("navigate", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("changes the path through history.pushState", () => {
    navigate("/projects/abc");
    expect(window.location.pathname).toBe("/projects/abc");
  });

  it("emits popstate so the SPA router can react", () => {
    const listener = vi.fn();
    window.addEventListener("popstate", listener);
    try {
      navigate("/some-path");
      expect(listener).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener("popstate", listener);
    }
  });

  it("keeps the query string passed in the argument", () => {
    navigate("/x?q=1");
    expect(window.location.search).toBe("?q=1");
  });
});
