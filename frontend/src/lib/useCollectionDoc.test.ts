import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

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
