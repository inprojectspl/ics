import { describe, it, expect } from "vitest";
import { annotateIntraline, pairForSplit, parseUnifiedDiff } from "./parseUnifiedDiff";

const diff = (...lines: string[]) => lines.join("\n") + "\n";
/** The side-by-side view pipeline: parse, then highlights, then column pairing. */
const split = (...lines: string[]) =>
  pairForSplit(annotateIntraline(parseUnifiedDiff(diff(...lines))));

describe("parseUnifiedDiff", () => {
  it("gives no lines for an empty diff", () => {
    expect(parseUnifiedDiff("")).toEqual([]);
  });

  it("skips file headers and keeps the hunk header", () => {
    const lines = parseUnifiedDiff(
      diff("--- v1/a.md", "+++ v2/a.md", "@@ -1,2 +1,2 @@", " context"),
    );
    expect(lines[0]).toEqual({ kind: "hunk", header: "@@ -1,2 +1,2 @@" });
    expect(lines).toHaveLength(2);
  });

  it("keeps the input order: removed before added", () => {
    const lines = parseUnifiedDiff(diff("@@ -1,2 +1,2 @@", "-a", "+a1", " ctx"));
    expect(lines.map((l) => l.kind)).toEqual(["hunk", "remove", "add", "context"]);
  });

  it("numbers lines continuously through context and changes", () => {
    const lines = parseUnifiedDiff(diff("@@ -10,3 +20,3 @@", " ctx", "-old", "+new", " ctx2"));
    expect(lines[1]).toMatchObject({ leftNo: 10, rightNo: 20 });
    expect(lines[2]).toMatchObject({ leftNo: 11, rightNo: null });
    expect(lines[3]).toMatchObject({ leftNo: null, rightNo: 21 });
    expect(lines[4]).toMatchObject({ leftNo: 12, rightNo: 22 });
  });

  it("handles several hunks, resetting the numbering", () => {
    const lines = parseUnifiedDiff(diff("@@ -1,1 +1,1 @@", " a", "@@ -50,1 +60,1 @@", " b"));
    expect(lines[1]).toMatchObject({ leftNo: 1, rightNo: 1 });
    expect(lines[3]).toMatchObject({ leftNo: 50, rightNo: 60 });
  });
});

describe("annotateIntraline", () => {
  it("gives a paired change intraline highlights", () => {
    const lines = annotateIntraline(
      parseUnifiedDiff(diff("@@ -1,1 +1,1 @@", "-Revenue: 134 thousand", "+Revenue: 141 thousand")),
    );
    const added = lines[2]!;
    if (added.kind === "hunk") throw new Error("expected an added line");
    expect(added.segments?.filter((s) => s.changed).map((s) => s.text)).toEqual(["141"]);
  });

  it("leaves context and one-sided lines unhighlighted", () => {
    const lines = annotateIntraline(parseUnifiedDiff(diff("@@ -1,2 +1,2 @@", " ctx", "+new")));
    for (const line of lines.slice(1)) {
      if (line.kind === "hunk") continue;
      expect(line.segments ?? null).toBeNull();
    }
  });
});

describe("pairForSplit", () => {
  it("puts context on both sides with the hunk's line numbers", () => {
    expect(split("@@ -5,1 +7,1 @@", " text")[1]).toEqual({
      kind: "context",
      left: "text",
      right: "text",
      leftNo: 5,
      rightNo: 7,
    });
  });

  it("pairs a removal with an addition into one change row", () => {
    expect(split("@@ -1,1 +1,1 @@", "-old", "+new")[1]).toMatchObject({
      kind: "change",
      left: "old",
      right: "new",
      leftNo: 1,
      rightNo: 1,
    });
  });

  it("gives extra added lines an empty left side", () => {
    const body = split("@@ -1,1 +1,3 @@", "-a", "+a1", "+a2", "+a3").slice(1);
    expect(body).toHaveLength(3);
    expect(body[0]).toMatchObject({ kind: "change", left: "a", right: "a1" });
    expect(body[1]).toMatchObject({
      kind: "add",
      left: null,
      right: "a2",
      leftNo: null,
    });
    expect(body[2]).toMatchObject({ kind: "add", left: null, right: "a3" });
  });

  it("gives extra removed lines an empty right side", () => {
    const body = split("@@ -1,3 +1,1 @@", "-a", "-b", "+a").slice(1);
    expect(body[0]).toMatchObject({ kind: "change", left: "a", right: "a" });
    expect(body[1]).toMatchObject({
      kind: "remove",
      left: "b",
      right: null,
      rightNo: null,
    });
  });

  it("gives a wholly added file an empty left column", () => {
    const body = split("@@ -0,0 +1,2 @@", "+line 1", "+line 2").slice(1);
    expect(body.every((r) => r.kind === "add" && r.left === null)).toBe(true);
  });

  it("closes the change block before the next hunk", () => {
    const rows = split("@@ -1,1 +1,1 @@", "-a", "+b", "@@ -9,1 +9,1 @@", " c");
    expect(rows.map((r) => r.kind)).toEqual(["hunk", "change", "hunk", "context"]);
  });

  it("carries the highlights to the matching sides of the row", () => {
    const row = split("@@ -1,1 +1,1 @@", "-pay 134 usd", "+pay 141 usd")[1]!;
    if (row.kind === "hunk") throw new Error("expected a change row");
    expect(row.leftSegments?.filter((s) => s.changed).map((s) => s.text)).toEqual(["134"]);
    expect(row.rightSegments?.filter((s) => s.changed).map((s) => s.text)).toEqual(["141"]);
  });
});
