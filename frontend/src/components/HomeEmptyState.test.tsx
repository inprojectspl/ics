import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { setLocale, t } from "../lib/i18n";
import type { AssetScope } from "../lib/useAssetFilter";
import { HomeEmptyState } from "./HomeEmptyState";

function renderState(over: { scope?: AssetScope; search?: string; filtered?: boolean } = {}) {
  const onClearFilters = vi.fn();
  render(
    <HomeEmptyState
      scope={over.scope ?? "all"}
      search={over.search ?? ""}
      filtered={over.filtered ?? false}
      onClearFilters={onClearFilters}
    />,
  );
  return { onClearFilters };
}

describe("HomeEmptyState", () => {
  it("a search of 2+ characters: no results, echoing the query", () => {
    renderState({ search: "reactor", filtered: true });
    expect(screen.getByText(t("homeEmpty.noResultsTitle", { query: "reactor" }))).toBeInTheDocument();
  });

  it("one character: a hint to type more", () => {
    renderState({ search: "r" });
    expect(screen.getByText(t("homeEmpty.noMatchesTitle"))).toBeInTheDocument();
  });

  it("active filters: a button to clear them", () => {
    const { onClearFilters } = renderState({ filtered: true, scope: "state:pinned" });
    expect(screen.getByText(t("homeEmpty.defaultTitle"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("filters.clear") }));
    expect(onClearFilters).toHaveBeenCalledTimes(1);
  });

  it.each<AssetScope>(["all", "state:mine"])("scope %s: no second upload button (it is in the header)", (scope) => {
    renderState({ scope });
    expect(screen.getByText(t("homeEmpty.allTitle"))).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it.each<[AssetScope, Parameters<typeof t>[0]]>([
    ["state:pinned", "homeEmpty.pinnedTitle"],
    ["state:shared-with-me", "homeEmpty.sharedTitle"],
    ["admin:review", "homeEmpty.reviewTitle"],
  ])("scope %s has its own message", (scope, key) => {
    renderState({ scope });
    expect(screen.getByText(t(key))).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders the upload prompt in English", () => {
    setLocale("en", { persist: false });
    try {
      renderState();
      expect(screen.getByText("Upload your first document")).toBeInTheDocument();
    } finally {
      setLocale("en", { persist: false });
    }
  });
});
