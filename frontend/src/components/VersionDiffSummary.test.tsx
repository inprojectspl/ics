import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { DiffFileChange } from "../api";
import { VersionDiffSummary } from "./VersionDiffSummary";

const change = (over: Partial<DiffFileChange> = {}): DiffFileChange => ({
  path: "README.md",
  change: "modified",
  binary: false,
  added_lines: 2,
  removed_lines: 1,
  size_from: 100,
  size_to: 120,
  ...over,
});

describe("VersionDiffSummary", () => {
  it("an empty list says nothing changed", () => {
    render(<VersionDiffSummary files={[]} />);
    expect(screen.getByText(/No file changed/)).toBeInTheDocument();
  });

  it("groups changes and counts files per group", () => {
    render(
      <VersionDiffSummary
        files={[
          change(),
          change({ path: "new.md", change: "added" }),
          change({ path: "gone.md", change: "removed" }),
        ]}
      />,
    );
    for (const heading of ["Modified", "Added", "Removed"]) {
      expect(screen.getByText(heading)).toBeInTheDocument();
    }
    // Check counters within the row, since the same values repeat in
    // other groups.
    const modified = screen.getByText("README.md").closest("li")!;
    expect(within(modified).getByText("+2")).toBeInTheDocument();
    expect(within(modified).getByText("−1")).toBeInTheDocument();
  });

  it("is a summary: it does not expand content (the full screen does that)", () => {
    render(<VersionDiffSummary files={[change()]} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("a binary file shows its size instead of counters", () => {
    render(
      <VersionDiffSummary
        files={[
          change({
            path: "img/logo.png",
            change: "added",
            binary: true,
            added_lines: null,
            removed_lines: null,
            size_to: 24576,
          }),
        ]}
      />,
    );
    expect(screen.getByText(/binary · 24.0 KB/)).toBeInTheDocument();
  });

  it("missing counters (file over the limit) show \"~\"", () => {
    render(
      <VersionDiffSummary
        files={[change({ path: "bundle.js", added_lines: null, removed_lines: null })]}
      />,
    );
    // The change marker is also "~", so target the counter column tooltip.
    expect(screen.getByTitle("File too large: lines not counted")).toBeInTheDocument();
  });

  it("a change with no line differences does not show a misleading \"+0 -0\"", () => {
    // Bytes differ but lines are the same (e.g. a changed end-of-file newline).
    render(<VersionDiffSummary files={[change({ added_lines: 0, removed_lines: 0 })]} />);
    expect(screen.getByText("no line changes")).toBeInTheDocument();
    expect(screen.queryByText("+0")).not.toBeInTheDocument();
  });
});
