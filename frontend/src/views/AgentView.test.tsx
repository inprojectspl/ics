import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ApiError } from "../api/_core";
import type { AgentView as AgentViewData, AssetKind } from "../api";
import { AgentView } from "./AgentView";

const getAssetSummary = vi.fn();
const listAgentFiles = vi.fn();
const getAgentView = vi.fn();
const navigate = vi.fn();
const writeText = vi.fn();

vi.mock("../api", () => ({
  api: {
    getAssetSummary: (...a: unknown[]) => getAssetSummary(...a),
    listAgentFiles: (...a: unknown[]) => listAgentFiles(...a),
    getAgentView: (...a: unknown[]) => getAgentView(...a),
  },
}));
vi.mock("../lib/navigate", () => ({ navigate: (to: string) => navigate(to) }));
vi.mock("../components/ViewerChrome", () => ({
  ViewerChrome: ({ breadcrumbs }: { breadcrumbs: { label: string }[] }) => (
    <nav data-testid="crumbs">{breadcrumbs.map((b) => b.label).join(" / ")}</nav>
  ),
}));
// The real reader hydrates widgets (shiki, mermaid); the text is what counts here.
vi.mock("../components/MarkdownView", () => ({
  MarkdownView: ({ html }: { html: string }) => <div data-testid="rendered">{html}</div>,
}));

function summary(kind: AssetKind) {
  return { id: "a1", slug: "doc-one", title: "Doc One", kind, version: 2, my_role: "owner" };
}

function view(over: Partial<AgentViewData> = {}): AgentViewData {
  return {
    slug: "doc-one",
    kind: "md_single",
    path: "doc.md",
    content: "# Hello\n\nbody",
    html: "<h1>Hello</h1>",
    total_lines: 3,
    shown_lines: 3,
    size_bytes: 13,
    estimated_tokens: 4,
    agent_reads: 1,
    lines_per_read: 2000,
    truncated: false,
    version: 2,
    current_version: 2,
    ...over,
  };
}

function single(kind: AssetKind = "md_single") {
  listAgentFiles.mockResolvedValue({ kind, entry_path: "doc.md", files: [] });
}

function renderView(props: Partial<Parameters<typeof AgentView>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AgentView slug="doc-one" {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  Object.assign(navigator, { clipboard: { writeText } });
  writeText.mockResolvedValue(undefined);
});

describe("AgentView", () => {
  it("renders the agent's Markdown and switches to the raw text", async () => {
    getAssetSummary.mockResolvedValue(summary("md_single"));
    single();
    getAgentView.mockResolvedValue(view());
    renderView();

    expect(await screen.findByTestId("rendered")).toHaveTextContent("<h1>Hello</h1>");
    expect(getAgentView).toHaveBeenCalledWith("doc-one", {
      path: null,
      format: undefined,
      version: undefined,
    });
    expect(screen.getByText('ics_asset_read(slug_or_id="doc-one")')).toBeInTheDocument();
    expect(screen.getByText("3 lines")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Raw text" }));
    expect(screen.queryByTestId("rendered")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Raw text").textContent).toBe("# Hello\n\nbody");
    expect(window.localStorage.getItem("ics.agentViewMode")).toBe("source");

    fireEvent.click(screen.getByRole("button", { name: /Copy content/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("# Hello\n\nbody"));
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("reads a bundle's entry page as Markdown and lets the owner pick raw HTML", async () => {
    getAssetSummary.mockResolvedValue(summary("html_bundle"));
    listAgentFiles.mockResolvedValue({
      kind: "html_bundle",
      entry_path: "index.html",
      files: [
        { path: "index.html", size_bytes: 10 },
        { path: "logo.png", size_bytes: 10 },
        { path: "about.html", size_bytes: 10 },
      ],
    });
    getAgentView.mockResolvedValue(
      view({ kind: "html_bundle", path: "index.html", format: "markdown", agent_reads: 3 }),
    );
    renderView();

    await screen.findByTestId("rendered");
    expect(getAgentView).toHaveBeenCalledWith("doc-one", {
      path: "index.html",
      format: "markdown",
      version: undefined,
    });
    const picker = screen.getByRole("combobox");
    expect([...picker.querySelectorAll("option")].map((o) => o.value)).toEqual([
      "index.html",
      "about.html",
    ]);
    expect(screen.getByText(/in parts \(3\)/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Raw HTML" }));
    expect(navigate).toHaveBeenLastCalledWith("/v/doc-one/agent?p=index.html&fmt=raw");
    fireEvent.change(picker, { target: { value: "about.html" } });
    expect(navigate).toHaveBeenLastCalledWith("/v/doc-one/agent?p=about.html");
  });

  it("shows raw text without a mode switch and marks an archived, truncated read", async () => {
    getAssetSummary.mockResolvedValue(summary("html_bundle"));
    listAgentFiles.mockReturnValue(new Promise(() => {}));
    getAgentView.mockResolvedValue(
      view({
        kind: "html_bundle",
        path: "index.html",
        content: "<p>x</p>",
        html: null,
        truncated: true,
        total_lines: 9000,
        shown_lines: 1,
        version: 1,
      }),
    );
    // `?p=` is known, so the read does not wait for the file inventory.
    renderView({ path: "index.html", format: "raw", version: 1 });

    expect(await screen.findByLabelText("Raw text")).toHaveTextContent("<p>x</p>");
    expect(screen.queryByRole("radio", { name: "Preview" })).not.toBeInTheDocument();
    expect(screen.getByText("archived version v1")).toBeInTheDocument();
    expect(screen.getByText(/The preview shows the start of the file/)).toBeInTheDocument();
    expect(
      screen.getByText(
        'ics_asset_read(slug_or_id="doc-one", path="index.html", format="raw", version=1)',
      ),
    ).toBeInTheDocument();
  });

  it("explains a binary file instead of a raw error", async () => {
    getAssetSummary.mockResolvedValue(summary("md_single"));
    single();
    getAgentView.mockRejectedValue(new ApiError(415, null, "415", "binary_file"));
    renderView();

    expect(await screen.findByText(/This is a binary file/)).toBeInTheDocument();
  });

  it("says so when the file is empty", async () => {
    getAssetSummary.mockResolvedValue(summary("md_single"));
    single();
    getAgentView.mockResolvedValue(view({ content: "", html: "", total_lines: 0 }));
    renderView();

    expect(await screen.findByText("The file is empty.")).toBeInTheDocument();
  });
});
