import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { AssetSummary, Me } from "../api";
import { Home } from "./Home";

const listAssets = vi.fn();
const page = (items: unknown[], total = items.length) => ({ items, total, page: 1, page_size: 25 });
const myQuota = vi.fn();
const listProjects = vi.fn();
const searchAssets = vi.fn();
const toast = vi.fn();

vi.mock("../api", () => ({
  api: {
    listAssets: (...a: unknown[]) => listAssets(...a),
    myQuota: (...a: unknown[]) => myQuota(...a),
    listProjects: (...a: unknown[]) => listProjects(...a),
    searchAssets: (...a: unknown[]) => searchAssets(...a),
    deleteAsset: vi.fn(),
    renameAsset: vi.fn(),
    pinAsset: vi.fn(),
    unpinAsset: vi.fn(),
    listDocTypes: () => Promise.resolve([]),
  },
}));
vi.mock("../components/Toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("../components/ConfirmDialog", () => ({
  useConfirm: () => vi.fn().mockResolvedValue(true),
}));

const DEFAULT_SORT = { key: "updated", order: "desc" };

const user = { id: "u1", email: "a@example.com", display_name: null, role: "user" } as Me;

function mkAsset(i: number, over: Partial<AssetSummary> = {}): AssetSummary {
  return {
    id: `a${i}`,
    slug: `doc-${i}`,
    title: `Doc ${i}`,
    kind: "md_single",
    size_bytes: 100,
    version: 1,
    security_status: "clean",
    active_share_modes: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    my_role: "owner",
    ...over,
  } as AssetSummary;
}

function renderHome(me: Me = user) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Home me={me} />
    </QueryClientProvider>,
  );
  return client;
}

function docLinks() {
  return screen.queryAllByRole("link", { name: /^Doc \d+$/ });
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/");
  window.localStorage.clear();
  listAssets.mockResolvedValue(page([mkAsset(1), mkAsset(2, { pinned_at: "2026-01-02T00:00:00Z" })]));
  myQuota.mockResolvedValue({ used_bytes: 10, quota_bytes: 1000 });
  listProjects.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 });
  searchAssets.mockResolvedValue([]);
});

describe("Home", () => {
  it("lists the user's documents once every query has loaded", async () => {
    renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(2));
    expect(screen.getByRole("heading", { level: 1, name: "Documents" })).toBeInTheDocument();
    expect(listProjects).toHaveBeenCalledWith({ page_size: 200 });
  });

  it("shows the upload prompt when there are no documents", async () => {
    listAssets.mockResolvedValue(page([]));
    renderHome();
    expect(await screen.findByText("Upload your first document")).toBeInTheDocument();
    expect(docLinks()).toHaveLength(0);
  });

  it("shows an actionable error when the list query fails", async () => {
    listAssets.mockRejectedValue(new Error("500 Internal Server Error"));
    renderHome();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the documents");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("shows the scope from the address and titles the page after it", async () => {
    window.history.replaceState({}, "", "/?f=state:pinned");
    listAssets.mockResolvedValue(page([mkAsset(2, { pinned_at: "2026-01-02T00:00:00Z" })]));
    renderHome();
    await waitFor(() => expect(docLinks().map((a) => a.textContent)).toEqual(["Doc 2"]));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Favourites");
  });

  it("titles every sidebar scope", async () => {
    const cases: Array<[string, string]> = [
      ["/?f=state:mine", "My documents"],
      ["/?f=state:shared-with-me", "Shared with me"],
      ["/?f=admin:review", "To approve"],
      ["/", "Documents"],
    ];
    for (const [url, heading] of cases) {
      window.history.replaceState({}, "", url);
      const { unmount } = render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <Home me={{ ...user, role: "admin" } as Me} />
        </QueryClientProvider>,
      );
      expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(heading);
      unmount();
    }
  });

  it("narrows the list with a toolbar filter and clears it from the chips", async () => {
    const all = { ...page([mkAsset(1), mkAsset(2, { kind: "pdf_doc" })]), filter_counts: { "type:md_single": 1, "type:pdf_doc": 1 } };
    listAssets.mockResolvedValue(all);
    renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    listAssets.mockResolvedValue({ ...all, ...page([mkAsset(2, { kind: "pdf_doc" })]) });
    fireEvent.click(screen.getByRole("checkbox", { name: /PDF files/ }));
    await waitFor(() => expect(docLinks().map((a) => a.textContent)).toEqual(["Doc 2"]));
    expect(window.location.search).toContain("f=type%3Apdf_doc");
    fireEvent.keyDown(document, { key: "Escape" });
    const chips = screen.getByRole("group", { name: "Active filters" });
    listAssets.mockResolvedValue(all);
    fireEvent.click(within(chips).getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(docLinks()).toHaveLength(2));
  });

  it("uses server search for queries of two characters or more", async () => {
    renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(2));
    const [box] = screen.getAllByRole("searchbox");
    listAssets.mockResolvedValue(page([mkAsset(7)]));
    fireEvent.change(box!, { target: { value: "spec" } });
    await waitFor(() => expect(listAssets).toHaveBeenCalledWith(1, 25, undefined, expect.objectContaining({ q: "spec", facets: true })));
    await waitFor(() => expect(docLinks().map((a) => a.textContent)).toEqual(["Doc 7"]));
  });

  it("shows a search error separately from an empty result and can retry", async () => {
    renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(2));
    listAssets.mockRejectedValueOnce(new Error("500"));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "zz" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the documents");
    expect(screen.queryByText(/No results for/)).toBeNull();
    listAssets.mockResolvedValue(page([mkAsset(7)]));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Doc 7" })).toBeInTheDocument();
  });

  it("asks for more input instead of showing incomplete local title results", async () => {
    renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(2));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "t" } });
    expect(screen.getByRole("status")).toHaveTextContent("Enter at least two characters");
    expect(docLinks()).toHaveLength(0);
    expect(listAssets).toHaveBeenCalledTimes(1);
  });

  it("paginates on the server, keeping the entire result count", async () => {
    listAssets.mockResolvedValueOnce(page(Array.from({ length: 25 }, (_, i) => mkAsset(i + 1)), 30))
      .mockResolvedValueOnce({ ...page(Array.from({ length: 5 }, (_, i) => mkAsset(i + 26)), 30), page: 2 });
    renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(25));
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(docLinks()).toHaveLength(5));
    expect(listAssets).toHaveBeenLastCalledWith(2, 25, DEFAULT_SORT, expect.objectContaining({ scope: "all", filters: [] }));
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("returns to the previous page when deleting the last item shrinks the result", async () => {
    const first = Array.from({ length: 25 }, (_, i) => mkAsset(i + 1));
    listAssets.mockResolvedValueOnce(page(first, 26))
      .mockResolvedValueOnce({ ...page([mkAsset(26)], 26), page: 2 });
    const client = renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(25));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(docLinks().map((a) => a.textContent)).toEqual(["Doc 26"]));
    listAssets.mockResolvedValueOnce({ ...page([], 25), page: 2 }).mockResolvedValue(page(first, 25));
    await act(async () => { await client.invalidateQueries({ queryKey: ["assets"] }); });
    await waitFor(() => expect(docLinks()).toHaveLength(25));
    expect(listAssets).toHaveBeenLastCalledWith(1, 25, DEFAULT_SORT, expect.anything());
    expect(screen.queryByText("Upload your first document")).toBeNull();
  });

  it("searches a single digit as a valid document query", async () => {
    renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(2));
    listAssets.mockResolvedValue(page([mkAsset(1)]));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "1" } });
    await waitFor(() => expect(listAssets).toHaveBeenLastCalledWith(1, 25, undefined, expect.objectContaining({ q: "1" })));
    await waitFor(() => expect(docLinks()).toHaveLength(1));
  });

  it("ignores late search responses and clears immediately to the document list", async () => {
    renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(2));
    let resolveOld!: (value: ReturnType<typeof page>) => void;
    const old = new Promise<ReturnType<typeof page>>((resolve) => { resolveOld = resolve; });
    listAssets.mockReturnValueOnce(old);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "older" } });
    expect(docLinks()).toHaveLength(0);
    await waitFor(() => expect(listAssets).toHaveBeenLastCalledWith(1, 25, undefined, expect.objectContaining({ q: "older" })));
    const signal = listAssets.mock.calls.at(-1)![3].signal as AbortSignal;
    listAssets.mockResolvedValueOnce(page([mkAsset(9)]));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "newer" } });
    expect(signal.aborted).toBe(true);
    expect(await screen.findByRole("link", { name: "Doc 9" })).toBeInTheDocument();
    await act(async () => resolveOld(page([mkAsset(8)])));
    expect(screen.queryByRole("link", { name: "Doc 8" })).toBeNull();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });
    await waitFor(() => expect(docLinks().map((a) => a.textContent)).toEqual(["Doc 1", "Doc 2"]));
  });

  it("opens the upload dialog from the header button", async () => {
    renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(2));
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(screen.getByRole("dialog", { name: "Upload documents" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Organisation/ })).toBeChecked();
  });

  it("opens the upload dialog for `?add=upload` and drops the parameter", async () => {
    window.history.replaceState({}, "", "/?add=upload&x=1");
    renderHome();
    expect(await screen.findByRole("dialog", { name: "Upload documents" })).toBeInTheDocument();
    expect(window.location.search).toBe("?x=1");
  });

  it("shows the drop target while files are dragged over the page", async () => {
    renderHome();
    await waitFor(() => expect(docLinks()).toHaveLength(2));
    const drag = (type: string) => {
      const ev = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperty(ev, "dataTransfer", { value: { types: ["Files"] } });
      window.dispatchEvent(ev);
    };
    act(() => drag("dragenter"));
    expect(screen.getByText("Drop to upload to Documents")).toBeInTheDocument();
    act(() => drag("dragleave"));
    expect(screen.queryByText("Drop to upload to Documents")).toBeNull();
  });
});
