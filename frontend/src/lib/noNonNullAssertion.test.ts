import { describe, expect, it } from "vitest";

// No `!` non-null assertion in production code (ADR-0002, I3); narrow with a guard.
// `x!.y`, `x!)`, `x!;`, `x![`, `x!,` and `x!++` after an identifier, `)` or `]`.
const ASSERTION = /[A-Za-z0-9_)\]]!(?=[.);\],[]|\s*\+\+)/;

const sources = import.meta.glob<string>("../**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
});

describe("non-null assertions", () => {
  it("are not used in production code", () => {
    const hits = Object.entries(sources)
      .filter(([path]) => !/\.test\.tsx?$/.test(path) && !path.endsWith("test-setup.ts"))
      .flatMap(([path, text]) =>
        text
          .split("\n")
          .map((line, i) => ({ line: line.replace(/\/\/.*$/, ""), n: i + 1 }))
          .filter(({ line }) => ASSERTION.test(line))
          .map(({ n }) => `${path}:${n}`),
      );
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    expect(hits).toEqual([]);
  });
});
