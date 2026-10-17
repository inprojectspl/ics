import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AssetSort } from "../lib/assetSort";
import { AssetSortControl } from "./AssetSortControl";
import { resetMediaQueryCache } from "../lib/useMediaQuery";

afterEach(() => vi.restoreAllMocks());

function setup(sort: AssetSort = { key: "updated", order: "desc" }) {
  const onChange = vi.fn();
  render(<AssetSortControl sort={sort} onChange={onChange} />);
  return onChange;
}

function mockMobile() {
  resetMediaQueryCache();
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        matches: query.includes("max-width"),
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );
}

describe("AssetSortControl on desktop", () => {
  it("shows the active key and opens a menu with the current choice checked", () => {
    setup();
    const trigger = screen.getByRole("button", { name: "Sort by: Last changed, Newest first" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu", { name: "Sort by" });
    expect(within(menu).getByRole("menuitemradio", { name: "Last changed" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(within(menu).getByRole("menuitemradio", { name: "Newest first" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("picking a key uses its natural direction and closes the menu", () => {
    const onChange = setup();
    fireEvent.click(screen.getByRole("button", { name: /Sort by:/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Title" }));
    expect(onChange).toHaveBeenCalledWith({ key: "title", order: "asc" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("picking a direction keeps the key", () => {
    const onChange = setup({ key: "versions", order: "desc" });
    fireEvent.click(screen.getByRole("button", { name: /Sort by:/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Fewest first" }));
    expect(onChange).toHaveBeenCalledWith({ key: "versions", order: "asc" });
  });

  it("names the current direction on the trigger", () => {
    setup({ key: "title", order: "asc" });
    expect(screen.getByRole("button", { name: "Sort by: Title, A to Z" })).toHaveAttribute("aria-haspopup", "menu");
  });

  it("opens from the keyboard with the arrow key", () => {
    setup();
    fireEvent.keyDown(screen.getByRole("button", { name: /Sort by:/ }), { key: "ArrowDown" });
    expect(screen.getByRole("menu", { name: "Sort by" })).toBeInTheDocument();
  });

  it("closes on Escape and on a click outside", () => {
    setup();
    const trigger = screen.getByRole("button", { name: /Sort by:/ });
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("AssetSortControl on a phone", () => {
  it("opens a bottom sheet instead of the dropdown", async () => {
    mockMobile();
    const onChange = setup();
    fireEvent.click(screen.getByRole("button", { name: /Sort by:/ }));
    const sheet = screen.getByRole("dialog", { name: "Sort by" });
    // The sheet carries the same list; there is no separate dropdown.
    expect(screen.getAllByRole("menu")).toHaveLength(1);
    expect(sheet).toContainElement(screen.getByRole("menu"));
    expect(within(sheet).getByRole("menuitemradio", { name: "Last changed" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    fireEvent.click(within(sheet).getByRole("menuitemradio", { name: "Number of versions" }));
    expect(onChange).toHaveBeenCalledWith({ key: "versions", order: "desc" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
