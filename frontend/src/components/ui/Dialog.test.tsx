import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { t } from "../../lib/i18n";
import { Dialog } from "./Dialog";

describe("Dialog", () => {
  it("renders the title and children", () => {
    render(
      <Dialog title="My Title" onClose={() => {}}>
        <p>Body content</p>
      </Dialog>,
    );
    expect(screen.getByText("My Title")).toBeInTheDocument();
    expect(screen.getByText("Body content")).toBeInTheDocument();
  });

  it("renders an optional eyebrow above the title", () => {
    render(
      <Dialog title="Title" eyebrow="EYEBROW" onClose={() => {}}>
        x
      </Dialog>,
    );
    expect(screen.getByText("EYEBROW")).toBeInTheDocument();
  });

  it("has role=dialog and aria-modal", () => {
    render(<Dialog title="x" onClose={() => {}}>y</Dialog>);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("the close button calls onClose", () => {
    const onClose = vi.fn();
    render(<Dialog title="x" onClose={onClose}>y</Dialog>);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: t("common.close") }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Esc calls onClose", () => {
    const onClose = vi.fn();
    render(<Dialog title="x" onClose={onClose}>y</Dialog>);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("other keys do not call onClose", () => {
    const onClose = vi.fn();
    render(<Dialog title="x" onClose={onClose}>y</Dialog>);
    fireEvent.keyDown(document, { key: "Enter" });
    fireEvent.keyDown(document, { key: "a" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("a click on the backdrop calls onClose", () => {
    const onClose = vi.fn();
    render(<Dialog title="x" onClose={onClose}>y</Dialog>);
    // The backdrop is decoration for assistive tech; a pointer click on it closes.
    const backdrop = document.querySelector(".bg-scrim");
    expect(backdrop).toHaveAttribute("aria-hidden");
    fireEvent.click(backdrop as HTMLElement);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("a click inside the content does not call onClose (stopPropagation)", () => {
    const onClose = vi.fn();
    render(
      <Dialog title="x" onClose={onClose}>
        <button>Inner</button>
      </Dialog>,
    );
    fireEvent.click(screen.getByText("Inner"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("names the dialog by its title and moves focus into it", () => {
    render(
      <Dialog title="Window title" onClose={() => {}}>
        <input aria-label="field" />
      </Dialog>,
    );
    expect(screen.getByRole("dialog", { name: "Window title" })).toBeInTheDocument();
    // The first focusable element inside the panel: its close button.
    expect(document.activeElement).toBe(within(screen.getByRole("dialog")).getByRole("button", { name: t("common.close") }));
  });

  it("locks page scrolling and restores it after closing", () => {
    const { unmount } = render(<Dialog title="x" onClose={() => {}}>y</Dialog>);
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("Escape closes only the topmost layer", () => {
    const outer = vi.fn();
    const inner = vi.fn();
    render(
      <>
        <Dialog title="outer" onClose={outer}>a</Dialog>
        <Dialog title="inner" onClose={inner}>b</Dialog>
      </>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });
});
