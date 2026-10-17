import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Share2 } from "lucide-react";
import { t } from "../../lib/i18n";
import { mockMedia } from "../../test-media";
import { ActionSheet } from "./ActionSheet";
import { Drawer } from "./Drawer";
import { trapTab } from "./floating";
import { Popover } from "./Popover";
import { Sheet } from "./Sheet";
import { useOverlay } from "./useOverlay";

describe("ActionSheet", () => {
  it("lists the actions, runs one and closes", () => {
    const onClose = vi.fn();
    const run = vi.fn();
    render(
      <ActionSheet
        open
        title="document.md"
        onClose={onClose}
        actions={[
          { key: "s", label: "Share", icon: Share2, onClick: run },
          { key: "x", label: "Disabled", onClick: vi.fn(), disabled: true, disabledHint: "Reason" },
          { key: "r", label: "Mode", checked: true, onClick: vi.fn() },
        ]}
      />,
    );
    expect(screen.getByRole("dialog", { name: "document.md" })).toBeInTheDocument();
    expect(screen.getByText("Reason")).toBeInTheDocument();
    expect(screen.getByRole("menuitemradio", { name: "Mode" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("menuitem", { name: "Share" }));
    expect(run).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes from the backdrop and Escape, and unmounts after the exit", async () => {
    const onClose = vi.fn();
    const { rerender } = render(<ActionSheet open title="T" onClose={onClose} actions={[]} />);
    const backdrop = document.querySelector('[role="presentation"] > [aria-hidden]');
    fireEvent.click(backdrop as Element);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
    rerender(<ActionSheet open={false} title="T" onClose={onClose} actions={[]} />);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("Drawer and Sheet", () => {
  it("drawer moves focus inside, closes on Escape and returns focus", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Menu
          </button>
          <Drawer open={open} onClose={() => setOpen(false)} title="Navigation" side="right">
            <a href="/x">Link</a>
          </Drawer>
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Menu" });
    opener.focus();
    fireEvent.click(opener);
    const drawer = screen.getByRole("dialog", { name: "Navigation" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(drawer.contains(document.activeElement)).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.keyDown(document, { key: "Escape" });
    // Focus comes back at once; the panel leaves after its exit.
    expect(opener).toHaveFocus();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.body.style.overflow).toBe("");
  });

  it("sheet shows a title, footer and closes from its button", () => {
    const onClose = vi.fn();
    render(
      <Sheet open title="Filters" onClose={onClose} footer={<span>Footer</span>}>
        Content
      </Sheet>,
    );
    expect(screen.getByRole("heading", { name: "Filters" })).toBeInTheDocument();
    expect(screen.getByText("Footer")).toBeInTheDocument();
    const closes = screen.getAllByRole("button", { name: t("common.close") });
    fireEvent.click(closes[closes.length - 1] as HTMLElement);
    expect(onClose).toHaveBeenCalled();
  });
});

describe("Popover", () => {
  const setup = () =>
    render(
      <Popover
        label="Filters"
        trigger={(p) => (
          <button type="button" {...p}>
            Open filters
          </button>
        )}
        footer={({ close }) => (
          <button type="button" onClick={close}>
            Done
          </button>
        )}
      >
        {() => <input aria-label="Field" />}
      </Popover>,
    );

  it("anchors a dialog on desktop and closes from the footer", () => {
    mockMedia({ width: 1440 });
    setup();
    const trigger = screen.getByRole("button", { name: "Open filters" });
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const panel = screen.getByRole("dialog", { name: "Filters" });
    expect(trigger).toHaveAttribute("aria-controls", panel.id);
    expect(screen.getByLabelText("Field")).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes on a press outside", () => {
    mockMedia({ width: 1440 });
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Open filters" }));
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("becomes a bottom sheet on a phone", () => {
    mockMedia({ width: 390 });
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Open filters" }));
    const sheet = screen.getByRole("dialog", { name: "Filters" });
    expect(sheet).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("heading", { name: "Filters" })).toBeInTheDocument();
  });
});

describe("useOverlay", () => {
  function Layer({ name, onClose, modal = true }: { name: string; onClose: () => void; modal?: boolean }) {
    const ref = useRef<HTMLDivElement>(null);
    useOverlay(ref, true, { onClose, modal });
    return (
      <div ref={ref}>
        <button type="button">{name}</button>
      </div>
    );
  }

  it("Escape closes only the innermost overlay", () => {
    const outer = vi.fn();
    const inner = vi.fn();
    render(
      <>
        <Layer name="outer" onClose={outer} />
        <Layer name="inner" onClose={inner} />
      </>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });

  it("keeps the page locked until the last modal layer goes", () => {
    const { rerender } = render(
      <>
        <Layer name="a" onClose={vi.fn()} />
        <Layer name="b" onClose={vi.fn()} />
      </>,
    );
    expect(document.body.style.overflow).toBe("hidden");
    rerender(<Layer name="a" onClose={vi.fn()} />);
    expect(document.body.style.overflow).toBe("hidden");
    rerender(<></>);
    expect(document.body.style.overflow).toBe("");
  });
});

describe("trapTab", () => {
  it("wraps Tab from the last to the first element and back", () => {
    render(
      <div data-testid="box">
        <button type="button">A</button>
        <button type="button">B</button>
      </div>,
    );
    const box = screen.getByTestId("box");
    const [a, b] = screen.getAllByRole("button") as [HTMLElement, HTMLElement];
    // jsdom has no layout: offsetParent is null, so only the focused one counts.
    Object.defineProperty(HTMLElement.prototype, "offsetParent", { configurable: true, get: () => document.body });
    b.focus();
    const forward = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
    trapTab(forward, box);
    expect(a).toHaveFocus();
    expect(forward.defaultPrevented).toBe(true);
    const back = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, cancelable: true });
    trapTab(back, box);
    expect(b).toHaveFocus();
    const other = new KeyboardEvent("keydown", { key: "a", cancelable: true });
    trapTab(other, box);
    expect(other.defaultPrevented).toBe(false);
    delete (HTMLElement.prototype as { offsetParent?: unknown }).offsetParent;
  });

  it("swallows Tab in a container with nothing to focus", () => {
    render(<div data-testid="empty" />);
    const ev = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
    trapTab(ev, screen.getByTestId("empty"));
    expect(ev.defaultPrevented).toBe(true);
  });
});
