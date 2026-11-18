import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { AssetSummary } from "../api";
import { navigate } from "./navigate";
import { qk } from "./queries";
import { togglePin, useAssetActions, useEmptyTrash } from "./useAssetActions";

vi.mock("./navigate", () => ({ navigate: vi.fn() }));

const deleteAsset = vi.fn();
const restoreAsset = vi.fn();
const archiveAsset = vi.fn();
const unarchiveAsset = vi.fn();
const purgeAsset = vi.fn();
const emptyTrash = vi.fn();
const authConfig = vi.fn();
const renameAsset = vi.fn();
const pinAsset = vi.fn();
const unpinAsset = vi.fn();
const toast = vi.fn();

vi.mock("../api", () => ({
  api: {
    deleteAsset: (...a: unknown[]) => deleteAsset(...a),
    restoreAsset: (...a: unknown[]) => restoreAsset(...a),
    archiveAsset: (...a: unknown[]) => archiveAsset(...a),
    unarchiveAsset: (...a: unknown[]) => unarchiveAsset(...a),
    purgeAsset: (...a: unknown[]) => purgeAsset(...a),
    emptyTrash: (...a: unknown[]) => emptyTrash(...a),
    authConfig: () => authConfig(),
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
const confirm = vi.fn();
vi.mock("../components/ConfirmDialog", () => ({
  useConfirm: () => confirm,
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

function ProbeImpl({
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

// The trash retention comes from the server config through TanStack Query.
function Probe({ client = new QueryClient(), ...props }: { onChanged: () => void; onDeleted?: () => void; client?: QueryClient }) {
  return (
    <QueryClientProvider client={client}>
      <ProbeImpl {...props} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  confirm.mockResolvedValue(true);
  authConfig.mockResolvedValue({ trash_retention_days: 14 });
});

/** The undo of the last toast that offered one. */
function undoOfLastToast(): () => void {
  const call = [...toast.mock.calls].reverse().find((c: unknown[]) => c[2]);
  if (!call) throw new Error("no toast with an action");
  return call[2].onClick;
}

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

  it("says how long the trash keeps a document and undoes the delete", async () => {
    const onChanged = vi.fn();
    const client = new QueryClient();
    render(<Probe onChanged={onChanged} client={client} />);
    await waitFor(() => expect(client.getQueryData(qk.authConfig())).toBeDefined());
    // The hook has re-rendered with the server's retention.
    await waitFor(() => expect(api.actions.onDelete).toBeDefined());
    await act(async () => {});
    await act(() => api.actions.onDelete(asset));
    expect(confirm.mock.calls[0]?.[0].message).toContain("14 days");
    restoreAsset.mockResolvedValue({ id: "a1", slug: "doc-one", noop: false });
    onChanged.mockClear();
    await act(async () => undoOfLastToast()());
    expect(restoreAsset).toHaveBeenCalledWith("a1");
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("brings a reader back to the document it restored", async () => {
    render(<Probe onChanged={vi.fn()} onDeleted={vi.fn()} />);
    restoreAsset.mockResolvedValue({ id: "a1", slug: "doc-one", noop: false });
    await act(() => api.actions.onRestore(asset));
    expect(navigate).toHaveBeenCalledWith("/v/doc-one");
  });

  it("archives, and the toast's undo takes the document back out", async () => {
    const onChanged = vi.fn();
    render(<Probe onChanged={onChanged} />);
    archiveAsset.mockResolvedValue({});
    unarchiveAsset.mockResolvedValue({});
    await act(() => api.actions.onArchive(asset));
    expect(archiveAsset).toHaveBeenCalledWith("a1");
    expect(onChanged).toHaveBeenCalled();
    await act(async () => undoOfLastToast()());
    expect(unarchiveAsset).toHaveBeenCalledWith("a1");
  });

  it("takes an archived document out of the archive", async () => {
    render(<Probe onChanged={vi.fn()} />);
    unarchiveAsset.mockResolvedValue({});
    await act(() => api.actions.onArchive({ ...asset, archived_at: "2026-11-01T00:00:00Z" }));
    expect(unarchiveAsset).toHaveBeenCalledWith("a1");
    expect(archiveAsset).not.toHaveBeenCalled();
  });

  it("purges only after a confirmation", async () => {
    const onChanged = vi.fn();
    render(<Probe onChanged={onChanged} />);
    confirm.mockResolvedValueOnce(false);
    await act(() => api.actions.onPurge(asset));
    expect(purgeAsset).not.toHaveBeenCalled();
    purgeAsset.mockResolvedValue({ id: "a1", purged: true });
    await act(() => api.actions.onPurge(asset));
    expect(purgeAsset).toHaveBeenCalledWith("a1");
    expect(onChanged).toHaveBeenCalled();
  });

  it("empties the trash in batches until nothing is left", async () => {
    let empty: ReturnType<typeof useEmptyTrash> = async () => {};
    const expose = (next: typeof empty) => {
      empty = next;
    };
    function EmptyProbe() {
      const next = useEmptyTrash(vi.fn());
      useEffect(() => expose(next));
      return null;
    }
    render(<EmptyProbe />);
    emptyTrash.mockResolvedValueOnce({ purged: 500, remaining: 3 }).mockResolvedValueOnce({ purged: 3, remaining: 0 });
    await act(() => empty(503, "p1"));
    expect(emptyTrash).toHaveBeenCalledTimes(2);
    expect(emptyTrash).toHaveBeenCalledWith("p1");
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("503"), "success");
  });

  it("opens the share dialog for the picked asset", async () => {
    // The share dialog's project section reads through TanStack Query.
    render(<Probe onChanged={vi.fn()} />);
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
