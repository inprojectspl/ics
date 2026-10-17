/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const themeCss = readFileSync(resolve(__dirname, "theme.css"), "utf8");

describe("code font", () => {
  it("turns ligatures off for font-code and for bare pre/code", () => {
    expect(themeCss).toContain('--font-code--font-feature-settings: "liga" 0, "calt" 0;');
    expect(themeCss).toContain("--default-mono-font-family: var(--font-code);");
    expect(themeCss).toContain('--default-mono-font-feature-settings: "liga" 0, "calt" 0;');
  });
});
