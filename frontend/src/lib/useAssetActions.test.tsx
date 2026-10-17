import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { AssetSummary } from "../api";
import { togglePin, useAssetActions } from "./useAssetActions";

const deleteAsset = vi.fn();
const renameAsset = vi.fn();
const pinAsset = vi.fn();
const unpinAsset = vi.fn();
const toast = vi.fn();

vi.mock("../api", () => ({
  api: {
    deleteAsset: (...a: unknown[]) => deleteAsset(...a),
    renameAsset: (...a: unknown[]) => renameAsset(...a),
    pinAsset: (...a: unknown[]) => pinAsset(...a),
    unpinAsset: (...a: unknown[]) => unpinAsset(...a),
    // ShareDialog mounts in the "opens the share dialog" test and reads both
    // lists right away; without stubs they would cause unhandled rejections.
    listShares: vi.fn().mockResolvedValue([]),
    listAssetShares: vi.fn().mockResolvedValue([]),
    listProjectShares: vi.fn().mockResolvedValue([]),
    listProjects: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 }),
  },
}));
vi.mock("../components/Toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("../components/ConfirmDialog", () => ({
  useConfirm: () => vi.fn().mockResolvedValue(true),
}));

const asset = {
  id: "a1",
  slug: "doc-one",
  title: "Doc One",
  kind: "md_single",
  version: 1,
  size_bytes: 1,
  security_status: "clean",
  created_at: "2026-01-01T00:00:00Z",
  my_role: "owner",
} as AssetSummary;

type Api = ReturnType<typeof useAssetActions>;
let api: Api;

// Hands the latest hook result to the tests after each commit.
function exposeApi(next: Api) {
  api = next;
}

function Probe({
  onChanged,
  onDeleted,
}: {
  onChanged: () => void;
  onDeleted?: () => void;
}) {
  const actions = useAssetActions(onChanged, { onDeleted });
  useEffect(() => exposeApi(actions));
  return <div data-testid="dialogs">{actions.dialogs}</div>;
}

beforeEach(() => vi.clearAllMocks());

describe("useAssetActions", () => {
  it("renames through the api and refetches", async () => {
    const onChanged = vi.fn();
    render(<Probe onChanged={onChanged} />);
    await act(() => api.onCommitRename("a1", "New"));
    expect(renameAsset).toHaveBeenCalledWith("a1", "New");
    expect(onChanged).toHaveBeenCalled();
  });

  it("reports a failed rename instead of claiming success", async () => {
    renameAsset.mockRejectedValueOnce(new Error("boom"));
    const onChanged = vi.fn();
    render(<Probe onChanged={onChanged} />);
    await act(() => api.onCommitRename("a1", "New"));
    expect(toast).toHaveBeenCalledWith(expect.any(String), "error");
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("hands a confirmed delete to onDeleted instead of refetching", async () => {
    const onChanged = vi.fn();
    const onDeleted = vi.fn();
    render(<Probe onChanged={onChanged} onDeleted={onDeleted} />);
    await act(() => api.actions.onDelete(asset));
    expect(deleteAsset).toHaveBeenCalledWith("a1");
    expect(onDeleted).toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("refetches after a delete when the caller has nowhere to go", async () => {
    const onChanged = vi.fn();
    render(<Probe onChanged={onChanged} />);
    await act(() => api.actions.onDelete(asset));
    expect(onChanged).toHaveBeenCalled();
  });

  it("opens the share dialog for the picked asset", async () => {
    // The share dialog's project section reads through TanStack Query.
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Probe onChanged={vi.fn()} />
      </QueryClientProvider>,
    );
    act(() => api.actions.onShare(asset));
    await waitFor(() => expect(screen.getByText(/Doc One/)).toBeInTheDocument());
  });

  it("togglePin pins and unpins, reporting the new state", async () => {
    const onToggled = vi.fn();
    await togglePin("a1", false, onToggled);
    expect(pinAsset).toHaveBeenCalledWith("a1");
    expect(onToggled).toHaveBeenCalledWith(true);

    await togglePin("a1", true, onToggled);
    expect(unpinAsset).toHaveBeenCalledWith("a1");
    expect(onToggled).toHaveBeenCalledWith(false);
  });

  it("swallows a failed pin toggle rather than reporting a state that never happened", async () => {
    pinAsset.mockRejectedValueOnce(new Error("nope"));
    const onToggled = vi.fn();
    await togglePin("a1", false, onToggled);
    expect(onToggled).not.toHaveBeenCalled();
  });
});
