import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { initials } from "./initials";
import { LOCATION_EVENT, navigate, replaceUrl } from "./navigate";
import { readStoredUploadMode, useUploadMode } from "./uploadMode";
import { useLocation } from "./useLocation";

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  localStorage.clear();
});

describe("navigate and replaceUrl", () => {
  it("replaceUrl rewrites the address without history and tells subscribers", () => {
    const heard = vi.fn();
    window.addEventListener(LOCATION_EVENT, heard);
    const before = window.history.length;
    replaceUrl("/?f=state:mine");
    expect(window.location.search).toBe("?f=state:mine");
    expect(window.history.length).toBe(before);
    expect(heard).toHaveBeenCalledTimes(1);
    window.removeEventListener(LOCATION_EVENT, heard);
  });

  it("navigate scrolls to the top only for a new page", () => {
    const scroll = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    navigate("/?f=state:mine");
    expect(scroll).not.toHaveBeenCalled();
    navigate("/projects");
    expect(scroll).toHaveBeenCalledWith({ top: 0 });
  });
});

describe("useLocation", () => {
  it("follows pushState navigation and replaceUrl", () => {
    const { result } = renderHook(() => useLocation());
    expect(result.current.pathname).toBe("/");
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    act(() => navigate("/projects/abc"));
    expect(result.current.pathname).toBe("/projects/abc");
    act(() => replaceUrl("/projects/abc?tab=members"));
    expect(result.current.search.get("tab")).toBe("members");
  });
});

describe("recentProjects", () => {
  it("keeps the last five, newest first, and survives a reload", async () => {
    vi.resetModules();
    const mod = await import("./recentProjects");
    const { result } = renderHook(() => mod.useRecentProjects());
    expect(result.current).toEqual([]);
    act(() => {
      for (const s of ["a", "b", "c", "d", "e", "f"]) mod.rememberProject(s);
      mod.rememberProject("c");
    });
    expect(result.current).toEqual(["c", "f", "e", "d", "b"]);
    expect(JSON.parse(localStorage.getItem("ics-recent-projects") ?? "[]")).toEqual(["c", "f", "e", "d", "b"]);
    vi.resetModules();
    const again = await import("./recentProjects");
    expect(renderHook(() => again.useRecentProjects()).result.current).toEqual(["c", "f", "e", "d", "b"]);
  });

  it("ignores a garbled stored list", async () => {
    localStorage.setItem("ics-recent-projects", "{nope");
    vi.resetModules();
    const mod = await import("./recentProjects");
    expect(renderHook(() => mod.useRecentProjects()).result.current).toEqual([]);
  });
});

describe("uploadMode", () => {
  it("defaults to the organisation and remembers a choice", () => {
    expect(readStoredUploadMode()).toBe("org_sso");
    const { result } = renderHook(() => useUploadMode());
    act(() => result.current[1]("public"));
    expect(result.current[0]).toBe("public");
    expect(readStoredUploadMode()).toBe("public");
    localStorage.setItem("ics:default-upload-mode", "weird");
    expect(readStoredUploadMode()).toBe("org_sso");
  });
});

describe("initials", () => {
  it("takes the first letters of two words, else the start of the e-mail", () => {
    expect(initials("Mary Oliver", "m@example.com")).toBe("MO");
    expect(initials(null, "anna@example.com")).toBe("AE");
    expect(initials("  ", "bob@x.io")).toBe("BX");
    expect(initials("Zed", "z@x")).toBe("ZE");
  });
});
