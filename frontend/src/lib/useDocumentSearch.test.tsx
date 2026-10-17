import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { api, type AssetSummary } from "../api";
import { qk } from "./queries";
import { useDocumentSearch } from "./useDocumentSearch";

const hit = (slug: string) => ({ slug, title: slug } as AssetSummary);
const deferred = () => {
  let resolve!: (rows: AssetSummary[]) => void;
  const promise = new Promise<AssetSummary[]>((done) => { resolve = done; });
  return { promise, resolve };
};

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, ...renderHook(({ q }) => useDocumentSearch(q, 20), { initialProps: { q: "alpha" }, wrapper }) };
}

beforeEach(() => vi.restoreAllMocks());

it("aborts on a new input and ignores old responses even when the transport resolves them", async () => {
  const old = deferred();
  const recent = deferred();
  const search = vi.spyOn(api, "searchAssets").mockReturnValueOnce(old.promise).mockReturnValueOnce(recent.promise);
  const { result, rerender } = setup();
  await waitFor(() => expect(search).toHaveBeenCalledTimes(1));
  const oldSignal = search.mock.calls[0]![3]!;
  rerender({ q: "beta" });
  expect(oldSignal.aborted).toBe(true);
  expect(result.current.data).toBeUndefined();
  expect(result.current.isSearching).toBe(true);
  await waitFor(() => expect(search).toHaveBeenCalledTimes(2));
  await act(async () => recent.resolve([hit("new")]));
  await waitFor(() => expect(result.current.data?.[0]?.slug).toBe("new"));
  await act(async () => old.resolve([hit("old")]));
  expect(result.current.data?.[0]?.slug).toBe("new");
  rerender({ q: "" });
  expect(result.current.data).toBeUndefined();
  expect(result.current.isSearching).toBe(false);
});

it("does not display previous results during debounce and refreshes on asset mutations", async () => {
  const search = vi.spyOn(api, "searchAssets").mockResolvedValue([hit("first")]);
  const { result, rerender, client } = setup();
  await waitFor(() => expect(result.current.data?.[0]?.slug).toBe("first"));
  rerender({ q: "beta" });
  expect(result.current.data).toBeUndefined();
  search.mockResolvedValue([hit("second")]);
  await waitFor(() => expect(result.current.data?.[0]?.slug).toBe("second"));
  search.mockResolvedValue([hit("updated")]);
  await act(async () => { await client.invalidateQueries({ queryKey: qk.assets() }); });
  await waitFor(() => expect(result.current.data?.[0]?.slug).toBe("updated"));
});

it("keeps a network error distinct from a successful empty result", async () => {
  vi.spyOn(api, "searchAssets").mockRejectedValue(new Error("offline"));
  const { result } = setup();
  await waitFor(() => expect(result.current.error).toBeInstanceOf(Error));
  expect(result.current.data).toBeUndefined();
  expect(result.current.isSearching).toBe(false);
});
