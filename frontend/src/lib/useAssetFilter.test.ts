import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { filterKind, scopeHref, useAssetFilter } from "./useAssetFilter";
import { LOCATION_EVENT } from "./navigate";
import type { AssetSummary } from "../api";

function asset(over: Partial<AssetSummary> = {}): AssetSummary {
  return {
    id: over.id ?? Math.random().toString(36),
    slug: over.slug ?? "doc",
    title: over.title ?? "Doc",
    kind: over.kind ?? "md_single",
    size_bytes: 0,
    version: 1,
    updated_at: "2026-01-01T00:00:00Z",
    pinned_at: null,
    owner_id: "u",
    project_id: null,
    has_binding: false,
    security_status: "clean",
    security_bypass: false,
    active_share_modes: [],
    access_source: "owned",
    ...over,
  } as AssetSummary;
}

const titles = (list: AssetSummary[]) => list.map((a) => a.title);

describe("useAssetFilter", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("returns everything for the default `all` scope without filters", () => {
    const items = [asset({ title: "A" }), asset({ title: "B" })];
    const { result } = renderHook(() => useAssetFilter(items, ""));
    expect(result.current.scope).toBe("all");
    expect(result.current.filters).toEqual([]);
    expect(result.current.visible).toHaveLength(2);
  });

  it("reads the scope from the address, including the old /shared link (`state:shared-with-me`)", () => {
    window.history.replaceState({}, "", "/?f=state%3Ashared-with-me");
    const items = [
      asset({ title: "Mine" }),
      asset({ title: "Direct", access_source: "direct" }),
      asset({ title: "Via project", access_source: "project" }),
    ];
    const { result } = renderHook(() => useAssetFilter(items, ""));
    expect(result.current.scope).toBe("state:shared-with-me");
    expect(titles(result.current.visible)).toEqual(["Direct", "Via project"]);
  });

  it("scopes: mine, pinned and the review queue", () => {
    const items = [
      asset({ title: "Mine" }),
      asset({ title: "Legacy", access_source: undefined }),
      asset({ title: "Shared", access_source: "direct" }),
      asset({ title: "Pinned", access_source: "direct", pinned_at: "2026-01-01T00:00:00Z" }),
      asset({ title: "Crit", access_source: "direct", security_status: "critical" }),
      asset({ title: "Bypassed", access_source: "direct", security_status: "critical", security_bypass: true }),
    ];
    const read = (url: string) => {
      window.history.replaceState({}, "", url);
      return titles(renderHook(() => useAssetFilter(items, "")).result.current.visible);
    };
    expect(read("/?f=state%3Amine")).toEqual(["Mine", "Legacy"]);
    expect(read("/?f=state%3Apinned")).toEqual(["Pinned"]);
    expect(read("/?f=admin%3Areview")).toEqual(["Crit"]);
  });

  it("scopeCounts counts each scope over the whole list", () => {
    const items = [
      asset(),
      asset({ access_source: "project" }),
      asset({ pinned_at: "2026-01-01T00:00:00Z" }),
    ];
    const { result } = renderHook(() => useAssetFilter(items, ""));
    expect(result.current.scopeCounts).toMatchObject({
      all: 3,
      "state:mine": 2,
      "state:shared-with-me": 1,
      "state:pinned": 1,
      "admin:review": 0,
    });
  });

  it("joins values of one kind with OR and different kinds with AND", () => {
    const items = [
      asset({ title: "MD public", kind: "md_single", active_share_modes: ["public"] }),
      asset({ title: "PDF public", kind: "pdf_doc", active_share_modes: ["public"] }),
      asset({ title: "PDF none", kind: "pdf_doc" }),
      asset({ title: "HTML public", kind: "html_bundle", active_share_modes: ["public"] }),
    ];
    const { result } = renderHook(() => useAssetFilter(items, ""));
    act(() => result.current.toggleFilter("type:md_single"));
    act(() => result.current.toggleFilter("type:pdf_doc"));
    expect(titles(result.current.visible)).toEqual(["MD public", "PDF public", "PDF none"]);
    act(() => result.current.toggleFilter("state:public"));
    expect(titles(result.current.visible)).toEqual(["MD public", "PDF public"]);
    // A second click takes the filter off again.
    act(() => result.current.toggleFilter("type:md_single"));
    expect(titles(result.current.visible)).toEqual(["PDF public"]);
  });

  it("filters by state, source, project, document type, freshness and tags", () => {
    const items = [
      asset({ title: "Unshared" }),
      asset({ title: "Password", active_share_modes: ["password"] }),
      asset({ title: "Org only", active_share_modes: ["org_sso"] }),
      asset({ title: "Git", has_binding: true, project_id: "p1", doc_type: "adr", freshness: "superseded", tags: ["x"] }),
    ];
    const check = (f: Parameters<ReturnType<typeof useAssetFilter>["toggleFilter"]>[0]) => {
      window.history.replaceState({}, "", "/");
      const { result } = renderHook(() => useAssetFilter(items, ""));
      act(() => result.current.toggleFilter(f));
      return titles(result.current.visible);
    };
    expect(check("state:unshared")).toEqual(["Unshared", "Git"]);
    expect(check("state:password")).toEqual(["Password"]);
    expect(check("source:gitlab")).toEqual(["Git"]);
    expect(check("source:manual")).toEqual(["Unshared", "Password", "Org only"]);
    expect(check("project:p1")).toEqual(["Git"]);
    expect(check("doctype:adr")).toEqual(["Git"]);
    expect(check("fresh:superseded")).toEqual(["Git"]);
    expect(check("tag:x")).toEqual(["Git"]);
  });

  it("counts a filter under the other kinds but not its own", () => {
    const items = [
      asset({ kind: "md_single", active_share_modes: ["public"] }),
      asset({ kind: "pdf_doc", active_share_modes: ["public"] }),
      asset({ kind: "pdf_doc" }),
    ];
    const { result } = renderHook(() => useAssetFilter(items, ""));
    expect(result.current.counts.get("type:pdf_doc")).toBe(2);
    act(() => result.current.toggleFilter("state:public"));
    // Narrowed by the share filter...
    expect(result.current.counts.get("type:pdf_doc")).toBe(1);
    expect(result.current.counts.get("type:md_single")).toBe(1);
    // ...while the share kind still counts the whole scope.
    expect(result.current.counts.get("state:public")).toBe(2);
    expect(result.current.counts.get("state:unshared")).toBe(1);
  });

  it("counts within the scope", () => {
    window.history.replaceState({}, "", "/?f=state%3Amine");
    const items = [asset({ kind: "pdf_doc" }), asset({ kind: "pdf_doc", access_source: "direct" })];
    const { result } = renderHook(() => useAssetFilter(items, ""));
    expect(result.current.counts.get("type:pdf_doc")).toBe(1);
  });

  it("writes the filters to the address with replaceState and announces the change", () => {
    window.history.replaceState({}, "", "/?f=state%3Amine&x=1");
    const onLocation = vi.fn();
    window.addEventListener(LOCATION_EVENT, onLocation);
    const { result } = renderHook(() => useAssetFilter([asset()], ""));
    act(() => result.current.toggleFilter("type:pdf_doc"));
    const params = new URLSearchParams(window.location.search);
    expect(params.getAll("f")).toEqual(["state:mine", "type:pdf_doc"]);
    expect(params.get("x")).toBe("1");
    expect(onLocation).toHaveBeenCalled();
    act(() => result.current.clearFilters());
    expect(new URLSearchParams(window.location.search).getAll("f")).toEqual(["state:mine"]);
    expect(result.current.scope).toBe("state:mine");
    window.removeEventListener(LOCATION_EVENT, onLocation);
  });

  it("reads the filters from the address on mount and skips garbage", () => {
    window.history.replaceState({}, "", "/?f=doctype%3Adesign&f=bogus&f=&f=doctype%3Adesign&f=state%3Apinned&f=state%3Amine");
    const items = [
      asset({ title: "D", doc_type: "design", pinned_at: "2026-01-01T00:00:00Z" }),
      asset({ title: "O", doc_type: "other", pinned_at: "2026-01-01T00:00:00Z" }),
    ];
    const { result } = renderHook(() => useAssetFilter(items, ""));
    expect(result.current.filters).toEqual(["doctype:design"]);
    // The first scope in the address wins.
    expect(result.current.scope).toBe("state:pinned");
    expect(titles(result.current.visible)).toEqual(["D"]);
  });

  it("loads the state from the address on popstate", () => {
    const { result } = renderHook(() => useAssetFilter([asset()], ""));
    act(() => {
      window.history.pushState({}, "", "/?f=state%3Apinned&f=tag%3Aa");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(result.current.scope).toBe("state:pinned");
    expect(result.current.filters).toEqual(["tag:a"]);
  });

  it("filters the query by title, case-insensitively, falling back to the slug", () => {
    const items = [asset({ title: "Alpha" }), asset({ title: null as unknown as string, slug: "beta-doc" })];
    const { result, rerender } = renderHook(({ q }) => useAssetFilter(items, q), { initialProps: { q: "ALP" } });
    expect(result.current.visible).toHaveLength(1);
    rerender({ q: "beta" });
    expect(result.current.visible.map((a) => a.slug)).toEqual(["beta-doc"]);
  });

  it("scopeHref and filterKind", () => {
    expect(scopeHref("all")).toBe("/");
    expect(scopeHref("state:mine")).toBe("/?f=state%3Amine");
    expect(filterKind("doctype:adr")).toBe("doctype");
  });
});
