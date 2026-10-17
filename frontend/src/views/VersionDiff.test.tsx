import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { DiffFileChange, DiffSummary, VersionRow } from "../api";
import { mockMedia } from "../test-media";
import { VersionDiff } from "./VersionDiff";

const getDoc = vi.fn();
const listVersions = vi.fn();
const diffVersions = vi.fn();
const diffVersionFile = vi.fn();
const navigate = vi.fn();

vi.mock("../api", () => ({
  api: {
    getDoc: (...a: unknown[]) => getDoc(...a),
    listVersions: (...a: unknown[]) => listVersions(...a),
    diffVersions: (...a: unknown[]) => diffVersions(...a),
    diffVersionFile: (...a: unknown[]) => diffVersionFile(...a),
  },
}));
vi.mock("../lib/navigate", () => ({ navigate: (to: string) => navigate(to) }));
vi.mock("../components/shell/PageContext", () => ({
  PageContext: ({ crumbs }: { crumbs: { label: string }[] }) => (
    <nav data-testid="crumbs">{crumbs.map((b) => b.label).join(" / ")}</nav>
  ),
}));
// The tree of changed files sits in the reader inspector; the stub keeps the
// slots the view fills so they can be asserted on.
vi.mock("../components/FileTree", () => ({
  FileTree: (p: { paths: string[]; onSelect: (path: string) => void; badgeFor: (path: string) => ReactNode }) => (
    <ul aria-label="tree">
      {p.paths.map((path) => (
        <li key={path}>
          <button type="button" onClick={() => p.onSelect(path)}>
            {path}
          </button>
          <span data-testid={`badge-${path}`}>{p.badgeFor(path)}</span>
        </li>
      ))}
    </ul>
  ),
}));
vi.mock("../components/DiffFileBlock", () => ({
  DiffFileBlock: (p: {
    file: DiffFileChange;
    mode: string;
    active: boolean;
    anchorId: string;
    load: (path: string) => Promise<string>;
  }) => (
    <section
      id={p.anchorId}
      data-testid="block"
      data-path={p.file.path}
      data-mode={p.mode}
      data-active={String(p.active)}
    >
      <button
        type="button"
        onClick={async () => {
          const text = await p.load(p.file.path);
          document.body.setAttribute("data-loaded", text);
        }}
      >
        load {p.file.path}
      </button>
    </section>
  ),
}));
vi.mock("../components/VersionPicker", () => ({
  VersionPicker: (p: {
    fromV: number;
    toV: number;
    onChange: (n: { fromV: number; toV: number }) => void;
  }) => (
    <button type="button" onClick={() => p.onChange({ fromV: 1, toV: 3 })}>
      picker {p.fromV}-{p.toV}
    </button>
  ),
}));

function row(version: number, over: Partial<VersionRow> = {}): VersionRow {
  return {
    version,
    size_bytes: 10,
    created_at: "2026-09-01T10:00:00Z",
    created_by: null,
    author: "Jane",
    author_email: null,
    is_current: false,
    ...over,
  };
}

function file(path: string, change: DiffFileChange["change"]): DiffFileChange {
  return {
    path,
    change,
    binary: false,
    added_lines: 1,
    removed_lines: 0,
    size_from: 1,
    size_to: 2,
  };
}

function summary(files: DiffFileChange[], over: Partial<DiffSummary> = {}): DiffSummary {
  return {
    kind: "md_collection",
    from_version: 2,
    to_version: 3,
    from_meta: row(2),
    to_meta: row(3),
    files,
    ...over,
  };
}

/** The "from → to" line next to the version picker. */
function caption(): HTMLElement {
  return screen.getByText((_, el) => el?.tagName === "P" && (el.textContent ?? "").includes("→"));
}

beforeEach(() => {
  vi.clearAllMocks();
  // Desktop: the file tree docks beside the diff and starts open.
  mockMedia({ width: 1440 });
  window.localStorage.clear();
  document.body.removeAttribute("data-loaded");
  getDoc.mockResolvedValue({ id: "a1", slug: "doc", title: "Handbook" });
  listVersions.mockResolvedValue([row(1), row(3, { is_current: true }), row(2)]);
  diffVersions.mockResolvedValue(
    summary([file("z.md", "removed"), file("b.md", "added"), file("a.md", "modified")]),
  );
  diffVersionFile.mockResolvedValue({ diff: "@@ -1 +1 @@" });
});

describe("VersionDiff", () => {
  it("defaults to the two newest versions and orders files modified, added, removed", async () => {
    render(<VersionDiff slug="doc" />);
    await waitFor(() => expect(screen.getAllByTestId("block")).toHaveLength(3));
    expect(diffVersions).toHaveBeenCalledWith("a1", 2, 3);
    expect(screen.getAllByTestId("block").map((b) => b.dataset.path)).toEqual([
      "a.md",
      "b.md",
      "z.md",
    ]);
    expect(screen.getByTestId("crumbs")).toHaveTextContent("Documents / Handbook / ");
    expect(screen.getByTestId("badge-a.md")).toHaveTextContent("~");
    expect(screen.getByTestId("badge-b.md")).toHaveTextContent("+");
    expect(screen.getByTestId("badge-z.md")).toHaveTextContent("−");
    expect(caption()).toHaveTextContent("v2");
    expect(caption()).toHaveTextContent("Jane");
  });

  it("shows a progress line until the summary arrives", async () => {
    diffVersions.mockReturnValue(new Promise(() => {}));
    render(<VersionDiff slug="doc" />);
    expect(await screen.findByText("Computing changes…")).toBeInTheDocument();
  });

  it("uses explicit from/to and falls back to bare version labels without meta", async () => {
    diffVersions.mockResolvedValue(summary([], { from_meta: null, to_meta: null }));
    render(<VersionDiff slug="doc" from={1} to={3} />);
    expect(
      await screen.findByText("No file changed between these versions."),
    ).toBeInTheDocument();
    expect(diffVersions).toHaveBeenCalledWith("a1", 1, 3);
    expect(caption()).toHaveTextContent("v1");
    expect(caption()).toHaveTextContent("v3");
  });

  it("tells a single-version document there is nothing to compare", async () => {
    listVersions.mockResolvedValue([row(1)]);
    render(<VersionDiff slug="doc" />);
    expect(await screen.findByText(/has only one version/)).toBeInTheDocument();
    expect(diffVersions).not.toHaveBeenCalled();
    expect(screen.queryByRole("list", { name: "tree" })).toBeNull();
  });

  it("shows the error when the document cannot be loaded", async () => {
    getDoc.mockRejectedValue(new Error("no access"));
    render(<VersionDiff slug="doc" />);
    expect(await screen.findByText("no access")).toBeInTheDocument();
  });

  it("shows the error when the diff request fails", async () => {
    diffVersions.mockRejectedValue(new Error("diff failed"));
    render(<VersionDiff slug="doc" />);
    expect(await screen.findByText("diff failed")).toBeInTheDocument();
  });

  it("navigates to the picked version pair", async () => {
    render(<VersionDiff slug="doc" />);
    fireEvent.click(await screen.findByRole("button", { name: /picker/ }));
    expect(navigate).toHaveBeenCalledWith("/v/doc/diff?from=1&to=3");
  });

  it("marks a file active and scrolls to it when picked in the tree", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    render(<VersionDiff slug="doc" />);
    await waitFor(() => expect(screen.getAllByTestId("block")).toHaveLength(3));
    fireEvent.click(screen.getByRole("button", { name: "b.md" }));
    const block = screen.getAllByTestId("block").find((b) => b.dataset.path === "b.md");
    expect(block?.dataset.active).toBe("true");
    expect(scroll).toHaveBeenCalled();
  });

  it("loads one file diff for the chosen versions", async () => {
    render(<VersionDiff slug="doc" />);
    fireEvent.click(await screen.findByRole("button", { name: "load a.md" }));
    await waitFor(() => expect(document.body.dataset.loaded).toBe("@@ -1 +1 @@"));
    expect(diffVersionFile).toHaveBeenCalledWith("a1", 2, 3, "a.md");
  });

  it("switches to split mode and remembers the choice", async () => {
    render(<VersionDiff slug="doc" />);
    await waitFor(() => expect(screen.getAllByTestId("block")).toHaveLength(3));
    fireEvent.click(screen.getByRole("radio", { name: /Side by side/ }));
    expect(screen.getAllByTestId("block")[0]?.dataset.mode).toBe("split");
    expect(window.localStorage.getItem("ics.diffMode")).toBe("split");
  });

  it("starts in the stored mode and survives a storage that throws", async () => {
    window.localStorage.setItem("ics.diffMode", "split");
    render(<VersionDiff slug="doc" />);
    await waitFor(() => expect(screen.getAllByTestId("block")).toHaveLength(3));
    expect(screen.getAllByTestId("block")[0]?.dataset.mode).toBe("split");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    fireEvent.click(screen.getByRole("radio", { name: /Unified/ }));
    expect(screen.getAllByTestId("block")[0]?.dataset.mode).toBe("unified");
  });

  it("falls back to unified when reading storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<VersionDiff slug="doc" />);
    await waitFor(() => expect(screen.getAllByTestId("block")).toHaveLength(3));
    expect(screen.getAllByTestId("block")[0]?.dataset.mode).toBe("unified");
  });
});
