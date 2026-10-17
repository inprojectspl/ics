import { describe, expect, it } from "vitest";
import { displayTitle } from "./displayTitle";

describe("displayTitle", () => {
  it("returns docTitle when activePath is empty", () => {
    expect(displayTitle("", "Nice File")).toBe("Nice File");
  });

  it("returns docTitle for md_single (activePath === entry_path)", () => {
    // Renaming Asset.title keeps the stored file name.
    expect(
      displayTitle("questions-for-the-vendor.md", "Nice File", "questions-for-the-vendor.md"),
    ).toBe("Nice File");
  });

  it("returns docTitle for the entry file of a collection", () => {
    expect(displayTitle("README.md", "My Collection", "README.md")).toBe("My Collection");
  });

  it("derives the title from the path for a sub-file of a collection", () => {
    expect(displayTitle("notes/2026/may.md", "My Collection", "README.md")).toBe("may");
  });

  it("strips the .md extension case-insensitively", () => {
    expect(displayTitle("notes/Plan.MD", "X", "README.md")).toBe("Plan");
  });

  it("falls back to docTitle for an empty basename", () => {
    expect(displayTitle(".md", "Fallback", "entry.md")).toBe("Fallback");
  });

  it("works when entryPath is undefined (backward compatibility)", () => {
    expect(displayTitle("notes/x.md", "DocTitle")).toBe("x");
  });
});
