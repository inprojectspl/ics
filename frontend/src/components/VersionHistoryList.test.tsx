import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { VersionRow } from "../api";
import { VersionHistoryList } from "./VersionHistoryList";

const row = (over: Partial<VersionRow> = {}): VersionRow => ({
  version: 1,
  size_bytes: 2048,
  created_at: "2026-01-02T10:30:00Z",
  created_by: "u1",
  author: "Jane Doe",
  author_email: null,
  is_current: false,
  ...over,
});

describe("VersionHistoryList", () => {
  const noActions = () => null;

  it("null means loading", () => {
    render(<VersionHistoryList versions={null} renderActions={noActions} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("an empty list says plainly there are no versions", () => {
    render(<VersionHistoryList versions={[]} renderActions={noActions} />);
    expect(screen.getByText("No versions.")).toBeInTheDocument();
  });

  it("renders the version, author, date and size", () => {
    render(<VersionHistoryList versions={[row()]} renderActions={noActions} />);
    expect(screen.getByText("v1")).toBeInTheDocument();
    const item = screen.getByRole("listitem");
    expect(item).toHaveTextContent("Jane Doe");
    expect(item).toHaveTextContent("2.0 KB");
    expect(item).toHaveTextContent("Jan 2, 2026");
  });

  it("the current version gets the \"Current\" badge", () => {
    render(
      <VersionHistoryList
        versions={[row({ version: 3, is_current: true }), row()]}
        renderActions={noActions}
      />,
    );
    expect(screen.getAllByText("Current")).toHaveLength(1);
  });

  it("a missing author does not break the row", () => {
    render(
      <VersionHistoryList
        versions={[row({ author: null, size_bytes: null })]}
        renderActions={noActions}
      />,
    );
    expect(screen.getByText("v1")).toBeInTheDocument();
  });

  it("renderActions gets the row and can skip the current version", () => {
    const onPick = vi.fn();
    render(
      <VersionHistoryList
        versions={[row({ version: 2, is_current: true }), row({ version: 1 })]}
        renderActions={(v) =>
          v.is_current ? null : <button onClick={() => onPick(v.version)}>View</button>
        }
      />,
    );
    const buttons = screen.getAllByText("View");
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]!);
    expect(onPick).toHaveBeenCalledWith(1);
  });

  it("shows the version change note when present", () => {
    render(
      <VersionHistoryList
        versions={[row({ version: 2, change_note: "New chapter on payments" }), row()]}
        renderActions={noActions}
      />,
    );
    const [withNote, withoutNote] = screen.getAllByRole("listitem");
    expect(withNote).toHaveTextContent("New chapter on payments");
    expect(withoutNote?.querySelector("p")).toBeNull();
  });

  it("an empty or missing change note adds nothing to the row", () => {
    render(
      <VersionHistoryList
        versions={[row({ version: 2, change_note: "" }), row({ change_note: null })]}
        renderActions={noActions}
      />,
    );
    for (const item of screen.getAllByRole("listitem")) {
      expect(item.querySelector("p")).toBeNull();
    }
  });
});
