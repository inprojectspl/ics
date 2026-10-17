import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { AssetSummary, Me } from "../api";
import { Home } from "./Home";

const listAssets = vi.fn();
const searchAssets = vi.fn();

vi.mock("../api", () => ({
  api: {
    listAssets: (...a: unknown[]) => listAssets(...a),
    searchAssets: (...a: unknown[]) => searchAssets(...a),
    myQuota: () => Promise.resolve({ used_bytes: 0, quota_bytes: 1000 }),
    listProjects: () => Promise.resolve({ items: [], total: 0, page: 1, page_size: 200 }),
    logout: vi.fn(),
    deleteAsset: vi.fn(),
    renameAsset: vi.fn(),
    pinAsset: vi.fn(),
    unpinAsset: vi.fn(),
    listDocTypes: () => Promise.resolve([]),
  },
}));
vi.mock("../components/Toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("../components/ConfirmDialog", () => ({ useConfirm: () => vi.fn() }));

const me = { id: "u1", email: "a@example.com", display_name: null, role: "user" } as Me;

function asset(title: string, over: Partial<AssetSummary>): AssetSummary {
  return {
    id: title,
    slug: title.toLowerCase(),
    title,
    kind: "md_single",
    size_bytes: 1,
    version: 1,
    security_status: "clean",
    active_share_modes: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    my_role: "owner",
    ...over,
  };
}

// The page preserves the server order, including relevance across pages.
const docs = [
  asset("Old", { version: 2, updated_at: "2026-01-02T00:00:00Z", created_at: "2026-01-02T00:00:00Z" }),
  asset("Busy", { version: 61, updated_at: "2026-01-09T00:00:00Z" }),
  asset("New", { version: 1, updated_at: "2026-01-05T00:00:00Z", created_at: "2026-01-05T00:00:00Z" }),
];

function renderHome() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Home me={me} />
    </QueryClientProvider>,
  );
}

function titles(): string[] {
  return screen
    .queryAllByRole("link", { name: /^(Old|Busy|New)$/ })
    .map((a) => a.textContent ?? "");
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  window.history.replaceState({}, "", "/");
  listAssets.mockResolvedValue({ items: [docs[1], docs[2], docs[0]], total: 3, page: 1, page_size: 25 });
  searchAssets.mockResolvedValue(docs);
});

describe("Home sorting", () => {
  it("shows the most recently changed documents first and asks the server for that order", async () => {
    renderHome();
    await waitFor(() => expect(titles()).toEqual(["Busy", "New", "Old"]));
    expect(listAssets).toHaveBeenCalledWith(1, 25, { key: "updated", order: "desc" }, expect.any(Object));
    expect(screen.getByText("3 documents")).toBeInTheDocument();
  });

  it("switches the key and direction, refetches in that order and remembers the choice", async () => {
    renderHome();
    await waitFor(() => expect(titles()).toHaveLength(3));

    fireEvent.click(screen.getByRole("button", { name: /^Sort by: Last changed/ }));
    listAssets.mockResolvedValue({ items: [docs[2], docs[0], docs[1]], total: 3 });
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Date created" }));
    await waitFor(() => expect(titles()).toEqual(["New", "Old", "Busy"]));
    expect(listAssets).toHaveBeenLastCalledWith(1, 25, { key: "created", order: "desc" }, expect.any(Object));

    fireEvent.click(screen.getByRole("button", { name: /^Sort by: Date created/ }));
    listAssets.mockResolvedValue({ items: [docs[1], docs[0], docs[2]], total: 3 });
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Oldest first" }));
    await waitFor(() => expect(titles()).toEqual(["Busy", "Old", "New"]));
    expect(listAssets).toHaveBeenLastCalledWith(1, 25, { key: "created", order: "asc" }, expect.any(Object));
    expect(JSON.parse(window.localStorage.getItem("ics.assetSort.home.u1") ?? "null")).toEqual({
      key: "created",
      order: "asc",
    });
  });

  it("starts from the remembered choice", async () => {
    listAssets.mockResolvedValue({ items: [docs[1], docs[0], docs[2]], total: 3 });
    window.localStorage.setItem(
      "ics.assetSort.home.u1",
      JSON.stringify({ key: "versions", order: "desc" }),
    );
    renderHome();
    await waitFor(() => expect(titles()).toEqual(["Busy", "Old", "New"]));
    expect(listAssets).toHaveBeenCalledWith(1, 25, { key: "versions", order: "desc" }, expect.any(Object));
  });

  it("defaults search to relevance and allows an explicit sort", async () => {
    window.localStorage.setItem("ics.assetSort.home.u1", JSON.stringify({ key: "title", order: "asc" }));
    renderHome();
    await waitFor(() => expect(titles()).toHaveLength(3));
    listAssets.mockResolvedValue({ items: [docs[0], docs[2], docs[1]], total: 3 });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "doc" } });
    await waitFor(() => expect(listAssets).toHaveBeenCalledWith(1, 25, undefined, expect.objectContaining({ q: "doc" })));
    await waitFor(() => expect(titles()).toEqual(["Old", "New", "Busy"]));
    fireEvent.click(screen.getByRole("button", { name: "Sort by: Relevance" }));
    listAssets.mockResolvedValue({ items: [docs[1], docs[2], docs[0]], total: 3 });
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Title" }));
    await waitFor(() => expect(listAssets).toHaveBeenLastCalledWith(1, 25, { key: "title", order: "asc" }, expect.objectContaining({ q: "doc" })));
    await waitFor(() => expect(titles()).toEqual(["Busy", "New", "Old"]));
  });
});
