import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { api } from "../api";
import { syncDocumentQueries } from "./documentQuerySync";
import { useDocumentSearch } from "./useDocumentSearch";

afterEach(() => vi.unstubAllGlobals());

it("refetches cached search after a real delete API call and leaves it intact on failure", async () => {
  let removed = false;
  let failDelete = false;
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      if (failDelete) return new Response(JSON.stringify({ detail: "failure" }), { status: 500 });
      removed = true;
      return new Response(null, { status: 204 });
    }
    return new Response(JSON.stringify(removed ? [] : [{ slug: "found", title: "Found" }]));
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  const stop = syncDocumentQueries(client);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result, unmount } = renderHook(() => useDocumentSearch("found", 20), { wrapper });
  try {
    await waitFor(() => expect(result.current.data).toHaveLength(1));
    await act(async () => {
      await api.deleteAsset("found");
    });
    await waitFor(() => expect(result.current.data).toEqual([]));
    const calls = fetcher.mock.calls.length;
    failDelete = true;
    await expect(api.deleteAsset("found")).rejects.toThrow();
    expect(fetcher.mock.calls.length).toBe(calls + 1);
  } finally {
    stop();
    unmount();
    client.clear();
  }
});
