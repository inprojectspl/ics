import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { Plus } from "lucide-react";
import * as nav from "../../lib/navigate";
import { AppLink } from "./AppLink";
import { Badge } from "./Badge";
import { Button, buttonClass } from "./Button";
import { ChipTabs } from "./ChipTabs";
import { DataList } from "./DataList";
import { Disclosure } from "./Disclosure";
import { IconButton, iconButtonClass } from "./IconButton";
import { PageHeader } from "./PageHeader";
import { PageToolbar } from "./PageToolbar";
import { PanelAction, PanelLink, PanelSection } from "./PanelSection";

describe("Button", () => {
  it("busy disables the button, keeps the label and marks it busy", () => {
    const onClick = vi.fn();
    render(
      <Button busy onClick={onClick} icon={<Plus aria-hidden />}>
        Save
      </Button>,
    );
    const b = screen.getByRole("button", { name: "Save" });
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute("aria-busy", "true");
    expect(b).toHaveAttribute("type", "button");
  });

  it("gives anchors the same look", () => {
    expect(buttonClass("danger-solid", "lg")).toContain("bg-danger");
    expect(iconButtonClass("secondary", "sm")).toContain("size-8");
  });
});

describe("IconButton", () => {
  it("is named by its label and shows it as a tooltip on mouse hover", () => {
    vi.useFakeTimers();
    try {
      render(<IconButton label="Collapse menu" icon={<Plus aria-hidden />} />);
      const b = screen.getByRole("button", { name: "Collapse menu" });
      fireEvent.pointerEnter(b, { pointerType: "mouse" });
      expect(screen.queryByRole("tooltip", { hidden: true })).not.toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(400);
      });
      expect(screen.getByRole("tooltip", { hidden: true })).toHaveTextContent("Collapse menu");
      fireEvent.keyDown(document, { key: "Escape" });
      expect(screen.queryByRole("tooltip", { hidden: true })).not.toBeInTheDocument();
      fireEvent.pointerEnter(b, { pointerType: "mouse" });
      act(() => {
        vi.advanceTimersByTime(400);
      });
      fireEvent.pointerLeave(b);
      expect(screen.queryByRole("tooltip", { hidden: true })).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("touch does not open the tooltip, keyboard focus does", () => {
    vi.useFakeTimers();
    try {
      render(<IconButton label="Search" icon={<Plus aria-hidden />} />);
      const b = screen.getByRole("button", { name: "Search" });
      fireEvent.pointerEnter(b, { pointerType: "touch" });
      act(() => {
        vi.advanceTimersByTime(400);
      });
      expect(screen.queryByRole("tooltip", { hidden: true })).not.toBeInTheDocument();
      const matches = vi.spyOn(Element.prototype, "matches").mockReturnValue(true);
      fireEvent.focus(b);
      expect(screen.getByRole("tooltip", { hidden: true })).toBeInTheDocument();
      matches.mockRestore();
      fireEvent.blur(b);
      expect(screen.queryByRole("tooltip", { hidden: true })).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("noTooltip leaves only the name", () => {
    vi.useFakeTimers();
    try {
      render(<IconButton label="Close" icon={<Plus aria-hidden />} noTooltip />);
      fireEvent.pointerEnter(screen.getByRole("button", { name: "Close" }), { pointerType: "mouse" });
      act(() => {
        vi.advanceTimersByTime(400);
      });
      expect(screen.queryByRole("tooltip", { hidden: true })).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("ChipTabs", () => {
  it("marks the active view, shows counts and reports a pick", () => {
    const onChange = vi.fn();
    render(
      <ChipTabs
        label="State"
        active="a"
        onChange={onChange}
        items={[
          { key: "a", label: "Wszyscy", count: 3 },
          { key: "b", label: "Zablokowani", count: 0 },
          { key: "c", label: "Bez licznika" },
        ]}
      />,
    );
    expect(screen.getByRole("navigation", { name: "State" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Wszyscy/ })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /Zablokowani/ })).not.toHaveAttribute("aria-current");
    fireEvent.click(screen.getByRole("button", { name: /Zablokowani/ }));
    expect(onChange).toHaveBeenCalledWith("b");
  });
});

describe("Disclosure", () => {
  it("folds its body and says so with aria-expanded", () => {
    render(
      <Disclosure title="Section" aside={<span>3</span>}>
        <p>Middle</p>
      </Disclosure>,
    );
    const toggle = screen.getByRole("button", { name: "Section" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const body = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(body).not.toBeVisible();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(body).toBeVisible();
  });

  it("can start open", () => {
    render(
      <Disclosure title="Expanded" defaultOpen>
        <p>Visible</p>
      </Disclosure>,
    );
    expect(screen.getByText("Visible")).toBeVisible();
  });
});

describe("layout pieces", () => {
  it("PageHeader renders one h1, the line under it and the actions", () => {
    render(<PageHeader title="Documents" description="3 documents" actions={<button type="button">Upload</button>} leading={<span>X</span>} />);
    expect(screen.getByRole("heading", { level: 1, name: "Documents" })).toBeInTheDocument();
    expect(screen.getByText("3 documents")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload" })).toBeInTheDocument();
  });

  it("PageToolbar is one toolbar with chips under it", () => {
    render(<PageToolbar start={<input aria-label="Search" />} end={<button type="button">Sort</button>} chips={<span>chip</span>} />);
    expect(screen.getByRole("toolbar")).toContainElement(screen.getByRole("button", { name: "Sort" }));
    expect(screen.getByText("chip")).toBeInTheDocument();
  });

  it("DataList is one named list, Badge shows its text", () => {
    render(
      <DataList label="Projects">
        <li>
          <Badge tone="warning" icon={<span>!</span>} title="Warning">
            State
          </Badge>
        </li>
      </DataList>,
    );
    expect(screen.getByRole("list", { name: "Projects" })).toBeInTheDocument();
    expect(screen.getByTitle("Warning")).toHaveTextContent("State");
  });

  it("PanelSection titles a block; its actions work as buttons and links", () => {
    const onClick = vi.fn();
    render(
      <PanelSection title="File" aside={<span>2</span>} last>
        <PanelAction icon={<span />} label="New" onClick={onClick} danger />
        <PanelAction icon={<span />} label="Blocked" onClick={onClick} disabled />
        <PanelLink href="/zip" icon={<span />} label="ZIP" download />
      </PanelSection>,
    );
    expect(screen.getByRole("heading", { name: "File" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(screen.getByRole("button", { name: "Blocked" })).toBeDisabled();
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "ZIP" })).toHaveAttribute("download");
  });
});

describe("AppLink", () => {
  it("routes a plain click inside the app without a page load", () => {
    const go = vi.spyOn(nav, "navigate").mockImplementation(() => {});
    render(<AppLink href="/projects">Projects</AppLink>);
    const link = screen.getByRole("link", { name: "Projects" });
    const ev = fireEvent.click(link);
    expect(ev).toBe(false);
    expect(go).toHaveBeenCalledWith("/projects");
  });

  it("leaves modifier clicks, API links, downloads and targets to the browser", () => {
    const go = vi.spyOn(nav, "navigate").mockImplementation(() => {});
    render(
      <>
        <AppLink href="/a">A</AppLink>
        <AppLink href="/api/assets/x/download">API</AppLink>
        <AppLink href="/b" download>
          B
        </AppLink>
        <AppLink href="/c" target="_blank">
          C
        </AppLink>
        <AppLink href="https://example.com">Ext</AppLink>
      </>,
    );
    fireEvent.click(screen.getByRole("link", { name: "A" }), { metaKey: true });
    fireEvent.click(screen.getByRole("link", { name: "API" }));
    fireEvent.click(screen.getByRole("link", { name: "B" }));
    fireEvent.click(screen.getByRole("link", { name: "C" }));
    fireEvent.click(screen.getByRole("link", { name: "Ext" }));
    expect(go).not.toHaveBeenCalled();
  });

  it("respects a handler that already prevented the default", () => {
    const go = vi.spyOn(nav, "navigate").mockImplementation(() => {});
    render(
      <AppLink href="/x" onClick={(e) => e.preventDefault()}>
        X
      </AppLink>,
    );
    fireEvent.click(screen.getByRole("link", { name: "X" }));
    expect(go).not.toHaveBeenCalled();
  });
});
