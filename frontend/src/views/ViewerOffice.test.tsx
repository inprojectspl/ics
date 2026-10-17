import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { fireEvent } from "@testing-library/react";
import type { AssetDoc } from "../api";
import { t } from "../lib/i18n";
import { Viewer } from "./Viewer";

// The office branch of the owner reader; the other kinds are covered in
// Viewer.test.tsx, which also documents the stubbed hooks below.
vi.mock("../api", () => ({ api: { getDoc: vi.fn(), listVersions: vi.fn() } }));

const docState = {
  doc: null as AssetDoc | null,
  html: "",
  error: null as string | null,
  docErrorStatus: null as number | null,
  docErrorCode: null as string | null,
};
vi.mock("../lib/useCollectionDoc", () => ({
  useCollectionDoc: () => ({
    ...docState,
    activePath: "",
    collectionCtx: null,
    openFile: vi.fn(),
    reload: vi.fn(),
  }),
}));
vi.mock("../lib/useSessionUser", () => ({ useSessionUser: () => null }));
vi.mock("../lib/useEntryFallback", () => ({ useEntryFallback: () => "unresolved" }));
vi.mock("../lib/useVersionPreview", () => ({
  useVersionPreview: () => ({
    previewVersion: null,
    meta: "v1",
    downloadHref: "/dl",
    staleNotice: null,
    historySection: null,
    historyPanel: <div>history</div>,
  }),
}));
vi.mock("../components/reader/useReaderActions", () => ({
  useReaderActions: () => ({ asset: null, project: null, menu: [], share: null, dialogs: null, onChanged: vi.fn(), assignProject: null }),
}));
vi.mock("../lib/useVaultFileActions", () => ({
  useVaultFileActions: () => ({ fileInputRef: { current: null } }),
}));
vi.mock("../components/shell/PageContext", () => ({
  PageContext: (p: { crumbs?: { label: string }[] }) => (
    <nav data-testid="crumbs">{p.crumbs?.map((b) => b.label).join(" / ") ?? ""}</nav>
  ),
}));
vi.mock("../components/OfficeDocument", () => ({
  OfficeDocument: (p: { html: string; downloadHref?: string; info?: { source_format: string } }) => (
    <article data-testid="office" data-download={p.downloadHref ?? ""}>
      {p.info?.source_format} {p.html}
    </article>
  ),
}));

beforeEach(() => {
  localStorage.clear();
  Object.assign(docState, {
    doc: null,
    html: "",
    error: null,
    docErrorStatus: null,
    docErrorCode: null,
  });
});

describe("Viewer office_doc", () => {
  it("renders the converted document with a download and no editor", () => {
    docState.doc = {
      id: "a1",
      slug: "doc",
      title: "Contract",
      kind: "office_doc",
      version: 1,
      size_bytes: 10,
      html: "<p>body</p>",
      my_role: "owner_file",
      document: { source_format: "docx", images: 0 },
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    docState.html = "converted";
    render(<Viewer slug="doc" />);
    expect(screen.getByTestId("office")).toHaveTextContent("docx converted");
    expect(screen.getByTestId("office").dataset.download).toBe("/dl");
    expect(screen.getByTestId("crumbs")).toHaveTextContent("Contract");
    expect(screen.queryByRole("button", { name: t("common.edit") })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: t("reader.inspectorShow") }));
    expect(screen.getByText("history")).toBeInTheDocument();
  });

  it("shows the review notice to a read-only role on a withheld document", () => {
    docState.error = "Bundle withheld";
    docState.docErrorStatus = 410;
    docState.docErrorCode = "bundle_withheld";
    render(<Viewer slug="doc" />);
    expect(screen.getByText("On hold")).toBeInTheDocument();
    expect(screen.queryByText("Bundle withheld")).toBeNull();
  });
});
