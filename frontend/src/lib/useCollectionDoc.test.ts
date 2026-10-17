import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

import type { AssetDoc } from "../api";
import { useCollectionDoc } from "./useCollectionDoc";

const doc: AssetDoc = {
  id: "a1",
  slug: "vault",
  title: "Vault",
  kind: "md_collection",
  version: 1,
  size_bytes: 10,
  entry_path: "index.md",
  html: "<p>index</p>",
  tree: ["index.md", "notes/a.md"],
  my_role: "owner_file",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const hrefFor = (p: string) => `#p=${p}`;

describe("useCollectionDoc collection context", () => {
  it("keeps its identity across re-renders with the same document", async () => {
    const opts = {
      key: "vault@current",
      loadDoc: vi.fn(async () => doc),
      loadFile: vi.fn(),
      hrefFor,
    };
    const { result, rerender } = renderHook(() => useCollectionDoc(opts));
    await waitFor(() => expect(result.current.collectionCtx).not.toBeNull());
    const first = result.current.collectionCtx;

    rerender();

    expect(result.current.collectionCtx).toBe(first);
    expect(first?.paths).toEqual(doc.tree);
  });
});

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

const vault: AssetDoc = { ...doc, tree: ["index.md", "a.md", "b.md"] };
const file = (path: string) => ({ slug: "vault", path, html: `<p>${path}</p>` });

describe("useCollectionDoc file loading", () => {
  it("keeps the last clicked file when answers arrive in reverse order", async () => {
    const a = deferred<ReturnType<typeof file>>();
    const b = deferred<ReturnType<typeof file>>();
    const loadFile = vi.fn((p: string) => (p === "a.md" ? a : b).promise);
    const { result } = renderHook(() =>
      useCollectionDoc({ key: "vault@current", loadDoc: async () => vault, loadFile, hrefFor }),
    );
    await waitFor(() => expect(result.current.doc).not.toBeNull());

    act(() => result.current.openFile("a.md"));
    act(() => result.current.openFile("b.md"));
    await act(async () => b.resolve(file("b.md")));
    await act(async () => a.resolve(file("a.md")));

    expect(result.current.activePath).toBe("b.md");
    expect(result.current.html).toBe("<p>b.md</p>");
  });

  it("drops a file answer that arrives after the document changed", async () => {
    const late = deferred<ReturnType<typeof file>>();
    const other: AssetDoc = { ...vault, id: "a2", slug: "other", html: "<p>other</p>" };
    let current = vault;
    const loadFile = vi.fn(() => late.promise);
    const { result, rerender } = renderHook(({ k }) =>
      useCollectionDoc({ key: k, loadDoc: async () => current, loadFile, hrefFor }),
      { initialProps: { k: "vault@current" } },
    );
    await waitFor(() => expect(result.current.doc?.slug).toBe("vault"));

    act(() => result.current.openFile("a.md"));
    current = other;
    rerender({ k: "other@current" });
    await waitFor(() => expect(result.current.doc?.slug).toBe("other"));
    await act(async () => late.resolve(file("a.md")));

    expect(result.current.activePath).toBe("index.md");
    expect(result.current.html).toBe("<p>other</p>");
  });

  it("follows the address through entry, a file, back and forward", async () => {
    const loadFile = vi.fn(async (p: string) => file(p));
    // The router passes the file named by the address, if any.
    let address: string | undefined;
    const onNavigate = vi.fn((p: string) => {
      address = p;
    });
    const { result, rerender } = renderHook(() =>
      useCollectionDoc({
        key: "vault@current",
        initialPath: address,
        loadDoc: async () => vault,
        loadFile,
        hrefFor,
        onNavigate,
      }),
    );
    await waitFor(() => expect(result.current.html).toBe("<p>index</p>"));

    act(() => result.current.openFile("b.md"));
    rerender();
    await waitFor(() => expect(result.current.html).toBe("<p>b.md</p>"));
    expect(loadFile).toHaveBeenCalledTimes(1);

    address = undefined; // back to the address without a file
    rerender();
    await waitFor(() => expect(result.current.html).toBe("<p>index</p>"));
    expect(result.current.activePath).toBe("index.md");

    address = "b.md"; // forward
    rerender();
    await waitFor(() => expect(result.current.html).toBe("<p>b.md</p>"));
    expect(result.current.activePath).toBe("b.md");
    expect(loadFile).toHaveBeenCalledTimes(2);
  });
});
