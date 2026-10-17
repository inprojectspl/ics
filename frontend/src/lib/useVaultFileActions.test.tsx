import type { ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, screen, fireEvent } from "@testing-library/react";
import { api } from "../api";
import { ConfirmProvider } from "../components/ConfirmDialog";
import { ToastProvider } from "../components/Toast";
import { useVaultFileActions } from "./useVaultFileActions";

const wrapper = ({ children }: { children: ReactNode }) => (
  <ToastProvider>
    <ConfirmProvider>{children}</ConfirmProvider>
  </ToastProvider>
);

const mkFileList = (name: string): FileList => {
  const file = new File(["x"], name, { type: "text/markdown" });
  return { 0: file, length: 1, item: () => file } as unknown as FileList;
};

function setup(overrides: { activePath?: string } = {}) {
  const reload = vi.fn().mockResolvedValue(undefined);
  const onEnterEditor = vi.fn();
  const { result } = renderHook(
    () =>
      useVaultFileActions({
        assetId: "asset-1",
        activePath: overrides.activePath ?? "notes/current.md",
        reload,
        onEnterEditor,
      }),
    { wrapper },
  );
  return { result, reload, onEnterEditor };
}

describe("useVaultFileActions", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("uploads a .md file through the API and reloads the document", async () => {
    const add = vi
      .spyOn(api, "addVaultFile")
      .mockResolvedValue({ id: "a", version: 2, added_path: "new.md", size_bytes: 1 });
    const { result, reload } = setup();

    await act(() => result.current.onPickedFile(mkFileList("new.md")));

    expect(add).toHaveBeenCalledWith("asset-1", expect.any(File));
    expect(reload).toHaveBeenCalled();
  });

  it("rejects a non-.md file without a request", async () => {
    const add = vi.spyOn(api, "addVaultFile");
    const { result, reload } = setup();

    await act(() => result.current.onPickedFile(mkFileList("image.png")));

    expect(add).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByText("Only .md files")).toBeInTheDocument();
  });

  it("does nothing for an empty selection", async () => {
    const add = vi.spyOn(api, "addVaultFile");
    const { result } = setup();

    await act(() => result.current.onPickedFile(null));

    expect(add).not.toHaveBeenCalled();
  });

  it("shows an upload error in a toast instead of throwing", async () => {
    vi.spyOn(api, "addVaultFile").mockRejectedValue(new Error("413 Payload Too Large"));
    const { result, reload } = setup();

    await act(() => result.current.onPickedFile(mkFileList("new.md")));

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByText(/The file is too large/)).toBeInTheDocument();
  });

  it("enters the editor for a new empty file only after the reload", async () => {
    vi.spyOn(api, "createEmptyVaultFile").mockResolvedValue({
      id: "a",
      version: 2,
      added_path: "notes/new.md",
      size_bytes: 0,
    });
    const order: string[] = [];
    const reload = vi.fn().mockImplementation(async () => void order.push("reload"));
    const onEnterEditor = vi.fn().mockImplementation(() => order.push("editor"));
    const { result } = renderHook(
      () =>
        useVaultFileActions({
          assetId: "asset-1",
          activePath: "notes/current.md",
          reload,
          onEnterEditor,
        }),
      { wrapper },
    );

    await act(() => result.current.onCreateEmptyFile("notes/new.md"));

    expect(reload).toHaveBeenCalledWith({ activeAfter: "notes/new.md" });
    expect(order).toEqual(["reload", "editor"]);
  });

  it("builds the move target from the file name and the folder", async () => {
    const move = vi.spyOn(api, "moveVaultFile").mockResolvedValue({
      id: "a",
      version: 2,
      from_path: "notes/current.md",
      to_path: "archive/current.md",
      entry_path: "README.md",
    });
    const { result, reload } = setup();

    await act(() => result.current.onMoveFile("notes/current.md", "archive"));

    expect(move).toHaveBeenCalledWith("asset-1", "notes/current.md", "archive/current.md");
    // The moved file was open, so the view follows it to the new path.
    expect(reload).toHaveBeenCalledWith({ activeAfter: "archive/current.md" });
  });

  it("moves to the root without a leading slash", async () => {
    const move = vi.spyOn(api, "moveVaultFile").mockResolvedValue({
      id: "a",
      version: 2,
      from_path: "notes/other.md",
      to_path: "other.md",
      entry_path: "README.md",
    });
    const { result, reload } = setup();

    await act(() => result.current.onMoveFile("notes/other.md", ""));

    expect(move).toHaveBeenCalledWith("asset-1", "notes/other.md", "other.md");
    // The moved file was not open, so the view stays where it was.
    expect(reload).toHaveBeenCalledWith({ activeAfter: "notes/current.md" });
  });

  /** Opens the confirm dialog and clicks the given button. `onDeleteFile`
   * waits on the `confirm()` promise, so it cannot be awaited before the
   * click; hence the two separate `act` calls. */
  async function deleteAndAnswer(
    trigger: () => Promise<void>,
    button: "Delete" | "Cancel",
  ): Promise<void> {
    let pending: Promise<void> | undefined;
    await act(async () => {
      pending = trigger();
    });
    fireEvent.click(screen.getByText(button));
    await act(async () => {
      await pending;
    });
  }

  it("asks before deleting and skips the API on cancel", async () => {
    const del = vi.spyOn(api, "deleteVaultFile");
    const { result, reload } = setup();

    await deleteAndAnswer(() => result.current.onDeleteFile("notes/current.md"), "Cancel");

    expect(del).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
  });

  it("moves to the new entry after deleting the open file", async () => {
    const del = vi.spyOn(api, "deleteVaultFile").mockResolvedValue({
      id: "a",
      version: 2,
      deleted_path: "notes/current.md",
      entry_path: "README.md",
      size_bytes: 1,
    });
    const { result, reload } = setup();

    await deleteAndAnswer(() => result.current.onDeleteFile("notes/current.md"), "Delete");

    expect(del).toHaveBeenCalledWith("asset-1", "notes/current.md");
    expect(reload).toHaveBeenCalledWith({ activeAfter: "README.md" });
  });

  it("keeps the active path when another file is deleted", async () => {
    vi.spyOn(api, "deleteVaultFile").mockResolvedValue({
      id: "a",
      version: 2,
      deleted_path: "notes/other.md",
      entry_path: "README.md",
      size_bytes: 1,
    });
    const { result, reload } = setup();

    await deleteAndAnswer(() => result.current.onDeleteFile("notes/other.md"), "Delete");

    expect(reload).toHaveBeenCalledWith({ activeAfter: "notes/current.md" });
  });

  it("shows a delete error in a toast", async () => {
    vi.spyOn(api, "deleteVaultFile").mockRejectedValue(new Error("409 Conflict"));
    const { result, reload } = setup();

    await deleteAndAnswer(() => result.current.onDeleteFile("notes/current.md"), "Delete");

    expect(reload).not.toHaveBeenCalled();
    expect(screen.getByText(/Conflict/)).toBeInTheDocument();
  });

  it("openFilePicker clicks the hidden input", () => {
    const { result } = setup();
    const input = document.createElement("input");
    const click = vi.spyOn(input, "click");
    result.current.fileInputRef.current = input;

    act(() => result.current.openFilePicker());

    expect(click).toHaveBeenCalled();
  });
});
