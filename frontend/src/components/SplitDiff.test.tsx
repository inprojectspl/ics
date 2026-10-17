import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { annotateIntraline, pairForSplit, parseUnifiedDiff } from "../lib/parseUnifiedDiff";
import { SplitDiff } from "./SplitDiff";

// The component gets ready rows; `DiffFileBlock` parses the diff once.
const diff = (...lines: string[]) =>
  pairForSplit(annotateIntraline(parseUnifiedDiff(lines.join("\n") + "\n")));

describe("SplitDiff", () => {
  it("an empty diff says the versions are identical", () => {
    render(<SplitDiff rows={[]} />);
    expect(screen.getByText(/The versions are identical/)).toBeInTheDocument();
  });

  it("a changed line sits in one row: old on the left, new on the right", () => {
    render(<SplitDiff rows={diff("@@ -1,1 +1,1 @@", "-old", "+new")} />);
    const rows = screen.getAllByRole("row");
    // rows[0] is the hunk header.
    const cells = within(rows[1]!).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("- old");
    expect(cells[3]).toHaveTextContent("+ new");
  });

  it("shows line numbers from both versions", () => {
    render(<SplitDiff rows={diff("@@ -10,1 +20,1 @@", " ctx")} />);
    const cells = within(screen.getAllByRole("row")[1]!).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("10");
    expect(cells[2]).toHaveTextContent("20");
  });

  it("an added line leaves the left cell empty", () => {
    render(<SplitDiff rows={diff("@@ -0,0 +1,1 @@", "+added")} />);
    const cells = within(screen.getAllByRole("row")[1]!).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("");
    expect(cells[1]).toHaveTextContent("");
    expect(cells[3]).toHaveTextContent("+ added");
  });

  it("the hunk header is a separate full-width row", () => {
    render(<SplitDiff rows={diff("@@ -1,2 +1,2 @@", " a")} />);
    const header = within(screen.getAllByRole("row")[0]!).getByRole("cell");
    expect(header).toHaveTextContent("@@ -1,2 +1,2 @@");
    expect(header).toHaveAttribute("colspan", "4");
  });

  it("highlights the changed part within a line", () => {
    render(
      <SplitDiff rows={diff("@@ -1,1 +1,1 @@", "-Revenue: 134 total", "+Revenue: 141 total")} />,
    );
    const cells = within(screen.getAllByRole("row")[1]!).getAllByRole("cell");
    // The changed number gets its own span, the shared prefix does not.
    expect(within(cells[1]!).getByText("134")).toBeInTheDocument();
    expect(within(cells[3]!).getByText("141")).toBeInTheDocument();
    // The full line text is still visible.
    expect(cells[3]).toHaveTextContent("+ Revenue: 141 total");
  });

  it("has a description for screen readers", () => {
    render(<SplitDiff rows={diff("@@ -1,1 +1,1 @@", " a")} />);
    expect(screen.getByRole("table")).toHaveAccessibleName(/the earlier version on the left/);
  });
});
