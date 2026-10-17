import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { AssetSummary } from "../api";
import { t } from "../lib/i18n";
import { InlineEditor } from "./InlineEditor";
import { UpdateAssetDialog } from "./UpdateAssetDialog";

const uploadVersion = vi.fn();
const editContent = vi.fn();
const getSource = vi.fn();

vi.mock("../api", () => ({
  api: {
    uploadVersion: (...a: unknown[]) => uploadVersion(...a),
    editContent: (...a: unknown[]) => editContent(...a),
    getSource: (...a: unknown[]) => getSource(...a),
  },
}));
vi.mock("./ConfirmDialog", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));

const file = new File(["# v2"], "a.md", { type: "text/markdown" });
vi.mock("../lib/directoryWalker", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../lib/directoryWalker")>();
  return { ...mod, walkDataTransfer: vi.fn(async () => [{ file, path: "a.md" }]) };
});

const asset = {
  id: "a1",
  slug: "doc",
  title: "Doc",
  kind: "md_single",
  version: 1,
} as AssetSummary;

function typeNote(value: string) {
  fireEvent.change(screen.getByLabelText(t("changeNote.label")), { target: { value } });
}

function drop() {
  const dropZone = screen.getByText(t("updateAsset.dropHere")).parentElement;
  if (!dropZone) throw new Error("drop zone not found");
  fireEvent.drop(dropZone, { dataTransfer: { items: [{}], files: [file] } });
}

beforeEach(() => {
  uploadVersion.mockReset().mockResolvedValue({ id: "a1", version: 2 });
  editContent.mockReset().mockResolvedValue({ id: "a1", version: 2, path: "a.md", size_bytes: 4 });
  getSource.mockReset().mockResolvedValue({ path: "a.md", content: "# v1" });
});

describe("change note in the upload dialog", () => {
  it("sends the typed note, trimmed, with the new version", async () => {
    const onUpdated = vi.fn();
    render(<UpdateAssetDialog asset={asset} onClose={vi.fn()} onUpdated={onUpdated} />);
    typeNote("  New chapter  ");
    drop();
    await waitFor(() => expect(onUpdated).toHaveBeenCalled());
    expect(uploadVersion).toHaveBeenCalledWith("a1", [{ file, path: "a.md" }], "New chapter");
  });

  it("sends no note when the field is left empty", async () => {
    render(<UpdateAssetDialog asset={asset} onClose={vi.fn()} onUpdated={vi.fn()} />);
    drop();
    await waitFor(() => expect(uploadVersion).toHaveBeenCalled());
    expect(uploadVersion.mock.calls[0]?.[2]).toBeUndefined();
  });
});

describe("file picker in the upload dialog", () => {
  it("uploads the picked file, for phones without drag and drop", async () => {
    const onUpdated = vi.fn();
    render(<UpdateAssetDialog asset={asset} onClose={vi.fn()} onUpdated={onUpdated} />);
    const input = screen.getByLabelText(t("updateAsset.pickFile"));
    expect(input).toHaveAttribute("accept", ".md");
    expect(input).not.toHaveAttribute("multiple");
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(onUpdated).toHaveBeenCalled());
    expect(uploadVersion).toHaveBeenCalledWith("a1", [{ file, path: "a.md" }], undefined);
  });

  it("offers files and a folder for a collection", () => {
    render(<UpdateAssetDialog asset={{ ...asset, kind: "md_collection" }} onClose={vi.fn()} onUpdated={vi.fn()} />);
    expect(screen.getByRole("button", { name: t("upload.pickFiles") })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("upload.pickFolder") })).toBeInTheDocument();
    expect(screen.getByText(t("updateAsset.kind", { kind: t("kind.mdCollection") }), { exact: false })).toBeInTheDocument();
  });
});

describe("inline editor layout", () => {
  it("takes the reading width instead of shrinking to its content", async () => {
    render(<InlineEditor assetId="a1" slug="doc" onSaved={vi.fn()} onCancel={vi.fn()} />);
    const textarea = await screen.findByDisplayValue("# v1");
    expect(textarea.closest("article")).toHaveClass("w-full", "max-w-(--reading-width)");
  });
});

describe("change note in the inline editor", () => {
  it("sends the typed note with the edited content", async () => {
    const onSaved = vi.fn();
    render(<InlineEditor assetId="a1" slug="doc" onSaved={onSaved} onCancel={vi.fn()} />);
    const textarea = await screen.findByDisplayValue("# v1");
    fireEvent.change(textarea, { target: { value: "# v2" } });
    typeNote("Fixed a typo");
    fireEvent.click(screen.getByRole("button", { name: t("inlineEditor.save") }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(2));
    expect(editContent).toHaveBeenCalledWith("a1", "# v2", undefined, "Fixed a typo");
  });
});
