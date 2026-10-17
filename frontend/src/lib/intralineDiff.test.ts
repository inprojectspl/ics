import { describe, it, expect } from "vitest";
import { intralineDiff } from "./intralineDiff";

const changed = (segs: { text: string; changed: boolean }[]) =>
  segs.filter((s) => s.changed).map((s) => s.text);

describe("intralineDiff", () => {
  it("has nothing to highlight in identical lines", () => {
    expect(intralineDiff("the same", "the same")).toBeNull();
  });

  it("marks the changed word on both sides", () => {
    const d = intralineDiff("Revenue: 134 thousand USD", "Revenue: 141 thousand USD")!;
    expect(changed(d.left)).toEqual(["134"]);
    expect(changed(d.right)).toEqual(["141"]);
  });

  it("leaves the common prefix and suffix untouched", () => {
    const d = intralineDiff("<div class='a'>x</div>", "<div class='b'>x</div>")!;
    expect(d.left.filter((s) => !s.changed).map((s) => s.text).join("")).toContain("<div class");
    expect(changed(d.left)).toEqual(["a"]);
    expect(changed(d.right)).toEqual(["b"]);
  });

  it("highlights only the fragment added in the middle", () => {
    const d = intralineDiff("font-size:13px", "font-size:13px;bold")!;
    expect(changed(d.left)).toEqual([]);
    expect(changed(d.right).join("")).toBe(";bold");
  });

  it("does not split the highlight at a space between changed words", () => {
    // A space matches a space, so without merging there would be two
    // highlights separated by an unmarked gap.
    const d = intralineDiff("alpha beta gamma", "alpha totally different gamma")!;
    expect(changed(d.right)).toEqual(["totally different"]);
  });

  it("joins the segments back into the original lines", () => {
    const left = "border-top:1px solid #26375c";
    const right = "border-top:2px dashed #26375c";
    const d = intralineDiff(left, right)!;
    expect(d.left.map((s) => s.text).join("")).toBe(left);
    expect(d.right.map((s) => s.text).join("")).toBe(right);
  });

  it("leaves completely different lines unhighlighted (it would be noise)", () => {
    // Only the spaces match, so similarity is measured by words.
    expect(intralineDiff("alpha beta gamma delta", "something else entirely here")).toBeNull();
  });

  it("skips a very long line (a minified bundle)", () => {
    const long = Array.from({ length: 400 }, (_, i) => `t${i}`).join(" ");
    expect(intralineDiff(long, long + " x")).toBeNull();
  });

  it("treats accented characters as part of one word", () => {
    const d = intralineDiff("crème brûlée naïve", "crème brûlée café")!;
    expect(changed(d.right)).toEqual(["café"]);
  });
});
