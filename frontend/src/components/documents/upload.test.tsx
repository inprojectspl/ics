import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { t } from "../../lib/i18n";
import { DropOverlay } from "./DropOverlay";
import { UploadDialog } from "./UploadDialog";

function dataTransfer(types: string[]): DataTransfer {
  return { types, items: [{}], files: [] } as unknown as DataTransfer;
}

function drag(type: string, types: string[], target: EventTarget = window) {
  const ev = new Event(type, { bubbles: true, cancelable: true }) as DragEvent;
  Object.defineProperty(ev, "dataTransfer", { value: dataTransfer(types) });
  act(() => {
    target.dispatchEvent(ev);
  });
  return ev;
}

describe("UploadDialog", () => {
  const base = () => ({
    mode: "org_sso" as const,
    onModeChange: vi.fn(),
    uploading: false,
    onPicked: vi.fn().mockResolvedValue(undefined),
    onDrop: vi.fn().mockResolvedValue(undefined),
    onClose: vi.fn(),
  });

  it("asks who sees the documents in one step with the files", () => {
    const p = base();
    render(<UploadDialog {...p} projectName="Alpha" />);
    expect(screen.getByRole("dialog", { name: t("upload.title") })).toBeInTheDocument();
    expect(screen.getByText(t("upload.toProject", { name: "Alpha" }))).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: new RegExp(t("upload.modeOrg")) })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: new RegExp(t("upload.modePublic")) }));
    expect(p.onModeChange).toHaveBeenCalledWith("public");
  });

  it("the pickers feed the chosen files and close the dialog", async () => {
    const p = base();
    render(<UploadDialog {...p} />);
    const input = screen.getByLabelText(t("upload.pickFiles"), { selector: "input" }) as HTMLInputElement;
    const click = vi.spyOn(input, "click");
    fireEvent.click(screen.getByRole("button", { name: t("upload.pickFiles") }));
    expect(click).toHaveBeenCalled();
    const file = new File(["# x"], "x.md", { type: "text/markdown" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(p.onClose).toHaveBeenCalled());
    expect(p.onPicked).toHaveBeenCalled();
    const folder = screen.getByLabelText(t("upload.pickFolder"), { selector: "input" });
    expect(folder).toHaveAttribute("webkitdirectory");
  });

  it("accepts a drop on its area and shows progress while uploading", async () => {
    const p = base();
    const { rerender } = render(<UploadDialog {...p} />);
    const zone = screen.getByText(t("upload.dropPrompt")).closest("div") as HTMLElement;
    fireEvent.dragOver(zone);
    expect(screen.getByText(t("uploadCard.dropHere"))).toBeInTheDocument();
    fireEvent.dragLeave(zone);
    fireEvent.drop(zone, { dataTransfer: { items: [{}], files: [] } });
    await waitFor(() => expect(p.onDrop).toHaveBeenCalled());
    rerender(<UploadDialog {...p} uploading />);
    expect(screen.getByRole("status")).toHaveTextContent(t("uploadCard.uploading"));
  });
});

describe("DropOverlay", () => {
  it("shows up only for dragged files and hands the drop over", () => {
    const onDrop = vi.fn();
    render(<DropOverlay target="Documents" audience="Organisation" onDrop={onDrop} />);
    drag("dragenter", ["text/plain"]);
    expect(screen.queryByText(t("upload.dropTo", { target: "Documents" }))).not.toBeInTheDocument();
    drag("dragenter", ["Files"]);
    expect(screen.getByText(t("upload.dropTo", { target: "Documents" }))).toBeInTheDocument();
    expect(drag("dragover", ["Files"]).defaultPrevented).toBe(true);
    drag("drop", ["Files"]);
    expect(onDrop).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(t("upload.dropTo", { target: "Documents" }))).not.toBeInTheDocument();
  });

  it("leaving the window hides it; nested enters are counted", () => {
    render(<DropOverlay target="X" audience="Y" onDrop={vi.fn()} />);
    drag("dragenter", ["Files"]);
    drag("dragenter", ["Files"]);
    drag("dragleave", ["Files"]);
    expect(screen.getByText("Y")).toBeInTheDocument();
    drag("dragleave", ["Files"]);
    expect(screen.queryByText("Y")).not.toBeInTheDocument();
  });

  it("leaves drops inside a dialog to the dialog, and stays off while disabled", () => {
    const onDrop = vi.fn();
    const { rerender } = render(
      <>
        <div role="dialog">
          <span>in the dialog</span>
        </div>
        <DropOverlay target="X" audience="Y" onDrop={onDrop} />
      </>,
    );
    drag("dragenter", ["Files"]);
    drag("drop", ["Files"], screen.getByText("in the dialog"));
    expect(onDrop).not.toHaveBeenCalled();
    expect(screen.queryByText("Y")).not.toBeInTheDocument();
    rerender(<DropOverlay target="X" audience="Y" onDrop={onDrop} disabled />);
    drag("dragenter", ["Files"]);
    expect(screen.queryByText("Y")).not.toBeInTheDocument();
  });
});
