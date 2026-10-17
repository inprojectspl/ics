import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Pencil, Trash2 } from "lucide-react";
import { mockMedia } from "../../test-media";
import { Menu } from "./Menu";
import type { MenuAction } from "./menuAction";

function actions(over: Partial<MenuAction>[] = []): MenuAction[] {
  const base: MenuAction[] = [
    { key: "a", label: "First", icon: Pencil, onClick: vi.fn() },
    { key: "b", label: "Second", onClick: vi.fn(), disabled: true, disabledHint: "Not now" },
    { key: "c", label: "Third", icon: Trash2, danger: true, onClick: vi.fn(), heading: "Group" },
  ];
  return base.map((a, i) => ({ ...a, ...over[i] }));
}

function setup(list = actions()) {
  render(
    <Menu
      label="Actions"
      actions={list}
      note="Note"
      trigger={(props) => (
        <button type="button" {...props}>
          Open
        </button>
      )}
    />,
  );
  return { list, trigger: screen.getByRole("button", { name: "Open" }) };
}

describe("Menu on desktop", () => {
  it("opens under the trigger with the first entry focused", () => {
    mockMedia({ width: 1440 });
    const { trigger } = setup();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu", { name: "Actions" });
    expect(trigger).toHaveAttribute("aria-controls", menu.id);
    expect(screen.getByText("Note")).toBeInTheDocument();
    expect(screen.getByText("Group")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "First" })).toHaveFocus();
  });

  it("moves with arrows, Home and End and wraps around", () => {
    mockMedia({ width: 1440 });
    const { trigger } = setup();
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu");
    const [first, second, third] = screen.getAllByRole("menuitem");
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(second).toHaveFocus();
    fireEvent.keyDown(menu, { key: "End" });
    expect(third).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(third).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Home" });
    expect(first).toHaveFocus();
  });

  it("ArrowUp on the trigger opens with the last entry focused", () => {
    mockMedia({ width: 1440 });
    const { trigger } = setup();
    fireEvent.keyDown(trigger, { key: "ArrowUp" });
    expect(screen.getAllByRole("menuitem").at(-1)).toHaveFocus();
  });

  it("runs an action and closes; a disabled one does nothing", () => {
    mockMedia({ width: 1440 });
    const { list, trigger } = setup();
    fireEvent.click(trigger);
    const disabled = screen.getByRole("menuitem", { name: "Second" });
    expect(disabled).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(disabled);
    expect(list[1]?.onClick).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "Third" }));
    expect(list[2]?.onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("Escape closes and hands focus back to the trigger", () => {
    mockMedia({ width: 1440 });
    const { trigger } = setup();
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("Tab and a press outside close it", () => {
    mockMedia({ width: 1440 });
    const { trigger } = setup();
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Tab" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("focuses the checked entry of a radio menu", () => {
    mockMedia({ width: 1440 });
    setup([
      { key: "x", label: "X", checked: false, onClick: vi.fn() },
      { key: "y", label: "Y", checked: true, onClick: vi.fn() },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByRole("menuitemradio", { name: "Y" })).toHaveFocus();
    expect(screen.getByRole("menuitemradio", { name: "Y" })).toHaveAttribute("aria-checked", "true");
  });
});

describe("Menu on a phone", () => {
  it("shows the same actions as an action sheet", () => {
    mockMedia({ width: 390 });
    const { list, trigger } = setup();
    fireEvent.click(trigger);
    expect(screen.queryByRole("menu", { hidden: false })).toBeInTheDocument();
    const sheet = screen.getByRole("dialog", { name: "Actions" });
    expect(sheet).toBeInTheDocument();
    expect(screen.getByText("Not now")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "First" }));
    expect(list[0]?.onClick).toHaveBeenCalledTimes(1);
  });
});
