/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const themeCss = readFileSync(resolve(__dirname, "theme.css"), "utf8");

// docs/DESIGN.md 4.3 and 16: components style themselves with the tokens from
// theme.css only. `@theme` switches the stock palettes off, so a stray
// `bg-blue-500` would silently render nothing; this test names it instead.

const sources = import.meta.glob<string>("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

const production = Object.entries(sources).filter(
  ([path]) => !/\.test\.tsx?$/.test(path) && !/test-[a-z-]+\.tsx?$/.test(path),
);

function tokens(prefix: string): Set<string> {
  const names = new Set<string>();
  for (const m of themeCss.matchAll(new RegExp(`--${prefix}-([a-z0-9-]+):`, "g"))) {
    if (m[1] && !m[1].includes("--")) names.add(m[1]);
  }
  return names;
}

const COLORS = tokens("color");
const COLOR_UTILITY =
  /(?<![\w-])(?:bg|text|border(?:-[trblxy])?|ring|ring-offset|outline|divide|from|via|to|fill|stroke|decoration|caret|placeholder)-([a-z][a-z0-9-]*[a-z0-9]|[a-z])(?=\/|[^\w-]|$)/g;
// `text-*` and `border-*` also carry sizes, alignment and widths.
const NOT_COLOR = new Set([
  ...tokens("text"),
  "left", "right", "center", "justify", "start", "end", "wrap", "nowrap", "balance", "pretty",
  "ellipsis", "clip", "none", "solid", "dashed", "dotted", "double", "hidden", "collapse",
  "separate", "spacing", "x", "y", "t", "b", "l", "r", "s", "e", "current", "transparent",
  "inherit", "offset", "inset", "auto", "clip-padding", "clip-border", "clip-content", "origin",
  "fixed", "local", "scroll", "cover", "contain", "repeat", "no-repeat", "center", "bottom",
  "top", "blend", "gradient", "linear", "from-font", "wavy", "underline", "sm", "md",
  // CSS property names inside inline SVG/HTML strings.
  "width", "linejoin", "linecap", "color", "mode", "radius", "decoration-color",
]);
const STOCK =
  /(?<![\w-])(?:bg|text|border|ring|fill|stroke|from|to|via|divide|outline|decoration|shadow)-(?:white|black|slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)\b/g;

function hits(pattern: RegExp, keep: (m: RegExpMatchArray) => boolean = () => true): string[] {
  return production.flatMap(([path, text]) =>
    text.split("\n").flatMap((line, i) =>
      [...line.matchAll(pattern)].filter(keep).map((m) => `${path}:${i + 1} ${m[0]}`),
    ),
  );
}

describe("design tokens", () => {
  it("theme.css defines the contract palette", () => {
    for (const name of ["canvas", "surface", "surface-subtle", "text-primary", "accent", "brand-mark"]) {
      expect(COLORS.has(name)).toBe(true);
    }
  });

  it("colour utilities use a theme token", () => {
    const unknown = hits(COLOR_UTILITY, (m) => {
      const name = m[1] ?? "";
      // Widths and offsets end in a number (`border-b-2`, `outline-offset-2`).
      if (NOT_COLOR.has(name) || /(^|-)\d+$/.test(name)) return false;
      return !COLORS.has(name);
    });
    expect(unknown).toEqual([]);
  });

  it("no raw hex colours, stock palettes or stock sizes in components", () => {
    expect(hits(STOCK)).toEqual([]);
    expect(hits(/(?:bg|text|border|fill|stroke|from|to)-\[#[0-9a-fA-F]{3,8}\]/g)).toEqual([]);
    expect(hits(/\btext-(?:xs|sm|base|lg|xl|[2-9]xl|small)\b(?!-)/g)).toEqual([]);
    expect(hits(/\brounded-(?:sm|md|lg|xl|2xl|3xl|pill|soft|round)\b(?!-)/g)).toEqual([]);
    expect(hits(/\bshadow-(?:sm|md|lg|xl|2xl|1|2|pop|chrome)\b(?!-)/g)).toEqual([]);
    expect(hits(/\bfont-(?:sans|serif|mono|display|body)\b(?!-)/g)).toEqual([]);
  });

  it("transitions name their properties", () => {
    expect(hits(/\btransition-all\b/g)).toEqual([]);
  });
});
