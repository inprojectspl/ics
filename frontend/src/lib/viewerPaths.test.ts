import { describe, expect, it } from "vitest";

import { buildVaultBreadcrumbs, canonicalPath, inferDefaultFolder } from "./viewerPaths";

describe("buildVaultBreadcrumbs", () => {
  it("links the collection root and leaves folders and the file plain", () => {
    const trail = buildVaultBreadcrumbs("Vault", "notes/2026/plan.md", "/v/vault");
    expect(trail).toEqual([
      { label: "Vault", href: "/v/vault" },
      { label: "notes" },
      { label: "2026" },
      { label: "plan" },
    ]);
  });

  it("leaves the collection root plain when there is no root route", () => {
    const trail = buildVaultBreadcrumbs("Vault", "notes/plan.md");
    expect(trail?.[0]).toStrictEqual({ label: "Vault" });
  });

  it("falls back to the plain title while the document is still loading", () => {
    expect(buildVaultBreadcrumbs("Vault", "", "/v/vault")).toBeUndefined();
  });
});

describe("inferDefaultFolder", () => {
  it("puts a new file next to the one being read", () => {
    expect(inferDefaultFolder("notes/2026/plan.md", [])).toBe("notes/2026");
  });

  it("drops it into the collection's single top folder when reading from the root", () => {
    expect(inferDefaultFolder("index.md", ["Research/a.md", "Research/b.md"])).toBe("Research");
  });

  it("leaves the folder empty when the collection has several top folders", () => {
    expect(inferDefaultFolder("index.md", ["A/a.md", "B/b.md"])).toBe("");
  });
});

describe("canonicalPath", () => {
  it("keeps a same-origin address as a path", () => {
    expect(canonicalPath(`${window.location.origin}/s/tok?x=1`)).toBe("/s/tok");
  });

  it("refuses an address from another instance", () => {
    expect(canonicalPath("https://elsewhere.example/s/tok")).toBeUndefined();
    expect(canonicalPath(undefined)).toBeUndefined();
  });
});
