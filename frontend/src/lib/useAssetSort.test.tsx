import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useAssetSort, type AssetListScope } from "./useAssetSort";

beforeEach(() => window.localStorage.clear());

const render = (scope: AssetListScope, userId: string) =>
  renderHook(({ s, u }) => useAssetSort(s, u), { initialProps: { s: scope, u: userId } });

describe("useAssetSort", () => {
  it("defaults to the last change, newest first", () => {
    const { result } = render("home", "u1");
    expect(result.current.sort).toEqual({ key: "updated", order: "desc" });
  });

  it("applies a picked value and keeps the same object between renders", () => {
    const { result, rerender } = render("home", "u1");
    act(() => result.current.setSort({ key: "title", order: "desc" }));
    const first = result.current.sort;
    expect(first).toEqual({ key: "title", order: "desc" });
    rerender({ s: "home", u: "u1" });
    expect(result.current.sort).toBe(first);
  });

  it("remembers the choice per user and per list", () => {
    const first = render("project", "u1");
    act(() => first.result.current.setSort({ key: "created", order: "asc" }));
    first.unmount();

    expect(render("project", "u1").result.current.sort).toEqual({ key: "created", order: "asc" });
    expect(render("project", "u2").result.current.sort).toEqual({ key: "updated", order: "desc" });
    expect(render("home", "u1").result.current.sort).toEqual({ key: "updated", order: "desc" });
  });

  it("re-reads storage when the user changes under the same hook", () => {
    window.localStorage.setItem(
      "ics.assetSort.home.u2",
      JSON.stringify({ key: "kind", order: "asc" }),
    );
    const { result, rerender } = render("home", "u1");
    act(() => result.current.setSort({ key: "title", order: "asc" }));
    rerender({ s: "home", u: "u2" });
    expect(result.current.sort).toEqual({ key: "kind", order: "asc" });
    // Stable across renders, so effects keyed on it do not refire.
    const current = result.current.sort;
    rerender({ s: "home", u: "u2" });
    expect(result.current.sort).toBe(current);
  });

  it("falls back to the default for a malformed stored value", () => {
    window.localStorage.setItem("ics.assetSort.home.u1", "{not json");
    expect(render("home", "u1").result.current.sort).toEqual({ key: "updated", order: "desc" });
  });
});
