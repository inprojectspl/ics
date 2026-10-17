import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { annotateIntraline, parseUnifiedDiff } from "../lib/parseUnifiedDiff";
import { UnifiedDiff } from "./UnifiedDiff";

// The component gets ready lines; `DiffFileBlock` parses the diff once.
const diff = (...lines: string[]) => annotateIntraline(parseUnifiedDiff(lines.join("\n") + "\n"));

describe("UnifiedDiff", () => {
  it("wraps long lines instead of scrolling, with the sign in its own column", () => {
    const { container } = render(<UnifiedDiff lines={diff("@@ -1,1 +1,1 @@", "-old", "+" + "long ".repeat(80))} />);
    const pre = container.querySelector("pre");
    expect(pre).not.toHaveClass("overflow-x-auto");
    const added = container.querySelectorAll("code > span")[2];
    expect(added).toHaveClass("whitespace-pre-wrap", "grid");
    expect(added?.firstElementChild?.textContent).toBe("+");
  });

  it("an empty diff says the versions are identical", () => {
    render(<UnifiedDiff lines={[]} />);
    expect(screen.getByText(/The versions are identical/)).toBeInTheDocument();
  });

  it("keeps the classic order: removed lines first, then added", () => {
    const { container } = render(
      <UnifiedDiff lines={diff("@@ -1,2 +1,2 @@", "-a", "-b", "+a1", "+b1", " ctx")} />,
    );
    const lines = Array.from(container.querySelectorAll("code > span")).map((n) => n.textContent);
    expect(lines).toEqual(["@@ -1,2 +1,2 @@", "-a", "-b", "+a1", "+b1", " ctx"]);
  });

  it("added lines come before the next context line", () => {
    const { container } = render(
      <UnifiedDiff lines={diff("@@ -1,3 +1,3 @@", " before", "-old", "+new", " after")} />,
    );
    const lines = Array.from(container.querySelectorAll("code > span")).map((n) => n.textContent);
    expect(lines).toEqual(["@@ -1,3 +1,3 @@", " before", "-old", "+new", " after"]);
  });

  it("highlights the changed part within a line", () => {
    render(<UnifiedDiff lines={diff("@@ -1,1 +1,1 @@", "-pay 134 usd", "+pay 141 usd")} />);
    expect(screen.getByText("134")).toBeInTheDocument();
    expect(screen.getByText("141")).toBeInTheDocument();
  });

  it("a wholly added file renders only added lines", () => {
    const { container } = render(<UnifiedDiff lines={diff("@@ -0,0 +1,2 @@", "+one", "+two")} />);
    const lines = Array.from(container.querySelectorAll("code > span")).map((n) => n.textContent);
    expect(lines).toEqual(["@@ -0,0 +1,2 @@", "+one", "+two"]);
  });
});
