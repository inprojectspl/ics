import { describe, expect, it } from "vitest";
import { foldText, matchesText } from "./text";

describe("text matching", () => {
  it("ignores case and Polish diacritics", () => {
    expect(foldText("Dział ŁĄKA")).toBe("dzial laka");
    expect(matchesText("Dział prawny", "dzial")).toBe(true);
    expect(matchesText("Fiber rollout Springfield", "  springfield ")).toBe(true);
    expect(matchesText("Customer portal", "contract")).toBe(false);
    expect(matchesText("anything", "")).toBe(true);
  });
});
