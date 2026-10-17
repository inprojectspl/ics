import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { AssetDoc } from "../api";
import { useCollectionDoc } from "../lib/useCollectionDoc";
import { MarkdownView } from "./MarkdownView";

const hydrate = vi.hoisted(() => vi.fn());
const mount = vi.hoisted(() => vi.fn(async () => {}));
vi.mock("../lib/hydrateMarkdown", () => ({ hydrateMarkdown: hydrate }));
vi.mock("../lib/mountWidgets", () => ({ mountWidgets: mount, repaintForTheme: vi.fn() }));

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
const loadDoc = async () => doc;
const loadFile = vi.fn();
const hrefFor = (p: string) => `#p=${p}`;

// A page that re-renders for reasons unrelated to the document, e.g. a dialog.
function Page() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const { html, collectionCtx } = useCollectionDoc({ key: "vault", loadDoc, loadFile, hrefFor });
  return (
    <>
      <button type="button" onClick={() => setDialogOpen((o) => !o)}>
        {dialogOpen ? "close" : "open"}
      </button>
      <MarkdownView html={html} theme="light" collection={collectionCtx} />
    </>
  );
}

describe("MarkdownView in a collection page", () => {
  it("does not hydrate the document again when the page re-renders", async () => {
    render(<Page />);
    await screen.findByText("index");
    await waitFor(() => expect(hydrate.mock.calls.at(-1)?.[1]).not.toBeNull());
    const hydratesAfterLoad = hydrate.mock.calls.length;
    const mountsAfterLoad = mount.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "open" }));
    fireEvent.click(screen.getByRole("button", { name: "close" }));

    expect(hydrate).toHaveBeenCalledTimes(hydratesAfterLoad);
    expect(mount).toHaveBeenCalledTimes(mountsAfterLoad);
  });
});
