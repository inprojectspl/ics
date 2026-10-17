/**
 * Unified diff to one line model shared by both view modes, so switching
 * modes costs no request or re-parse: `parseUnifiedDiff` -> `DiffLine[]`
 * (unified view), `annotateIntraline` adds highlights, `pairForSplit` pairs
 * lines for the side-by-side view.
 */

import { intralineDiff, type IntralineDiff, type Segment } from "./intralineDiff";

interface TextLine {
  text: string;
  leftNo: number | null;
  rightNo: number | null;
  /** Parts that differ from the paired line on the other side, see `annotateIntraline`. */
  segments?: Segment[];
}

// One variant per `kind` (rather than a union in the field) so `Extract` on
// `kind` narrows the type; column pairing works directly on `add`/`remove`.
export type DiffLine =
  | { kind: "hunk"; header: string }
  | ({ kind: "context" } & TextLine)
  | ({ kind: "add" } & TextLine)
  | ({ kind: "remove" } & TextLine);

export type SplitRow =
  | { kind: "hunk"; header: string }
  | {
      kind: "context" | "add" | "remove" | "change";
      left: string | null;
      right: string | null;
      leftNo: number | null;
      rightNo: number | null;
      leftSegments?: Segment[];
      rightSegments?: Segment[];
    };

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

export function parseUnifiedDiff(diff: string): DiffLine[] {
  const lines: DiffLine[] = [];
  let leftNo = 0;
  let rightNo = 0;

  for (const line of diff.split("\n")) {
    // File headers (`--- v1/x`, `+++ v2/x`) carry no content; the file name
    // is shown in the block header above the diff.
    if (line.startsWith("--- ") || line.startsWith("+++ ")) continue;

    const hunk = HUNK.exec(line);
    if (hunk) {
      leftNo = Number(hunk[1]) - 1;
      rightNo = Number(hunk[2]) - 1;
      lines.push({ kind: "hunk", header: line });
      continue;
    }
    if (line.startsWith("-")) {
      lines.push({
        kind: "remove",
        text: line.slice(1),
        leftNo: ++leftNo,
        rightNo: null,
      });
      continue;
    }
    if (line.startsWith("+")) {
      lines.push({
        kind: "add",
        text: line.slice(1),
        leftNo: null,
        rightNo: ++rightNo,
      });
      continue;
    }
    // `difflib` ends its output with an empty line after the final `\n`.
    if (line === "") continue;
    lines.push({
      kind: "context",
      text: line.startsWith(" ") ? line.slice(1) : line,
      leftNo: ++leftNo,
      rightNo: ++rightNo,
    });
  }
  return lines;
}

/**
 * Adds intraline highlights, as a separate pass so callers that only count
 * lines skip the LCS. Pairs each `-` block with the following `+` block, as
 * the split view does, so both modes highlight identically.
 */
export function annotateIntraline(lines: DiffLine[]): DiffLine[] {
  const out = [...lines];
  for (const [start, end] of changeBlocks(lines)) {
    const removed: number[] = [];
    const added: number[] = [];
    for (let i = start; i < end; i++) {
      const l = out[i];
      if (!l) continue;
      if (l.kind === "remove") removed.push(i);
      else if (l.kind === "add") added.push(i);
    }
    for (let k = 0; k < Math.min(removed.length, added.length); k++) {
      const leftAt = removed[k];
      const rightAt = added[k];
      if (leftAt === undefined || rightAt === undefined) continue;
      const li = out[leftAt];
      const ri = out[rightAt];
      if (li?.kind !== "remove" || ri?.kind !== "add") continue;
      const intra: IntralineDiff | null = intralineDiff(li.text, ri.text);
      if (!intra) continue;
      out[leftAt] = { ...li, segments: intra.left };
      out[rightAt] = { ...ri, segments: intra.right };
    }
  }
  return out;
}

/** `[start, end)` ranges of consecutive change blocks (`-`/`+` without context). */
function changeBlocks(lines: DiffLine[]): Array<[number, number]> {
  const blocks: Array<[number, number]> = [];
  let start: number | null = null;
  for (let i = 0; i <= lines.length; i++) {
    const kind = lines[i]?.kind;
    const inBlock = kind === "add" || kind === "remove";
    if (inBlock && start === null) start = i;
    if (!inBlock && start !== null) {
      blocks.push([start, i]);
      start = null;
    }
  }
  return blocks;
}

/**
 * Two-column layout: a `-` block is paired with the following `+` block, and
 * the surplus on the longer side gets an empty cell. Otherwise replacing one
 * line would show as a removal in one row and an addition in the next.
 * Layout only; highlights are already computed by `annotateIntraline`.
 */
export function pairForSplit(lines: DiffLine[]): SplitRow[] {
  const rows: SplitRow[] = [];
  let removed: Extract<DiffLine, { kind: "remove" }>[] = [];
  let added: Extract<DiffLine, { kind: "add" }>[] = [];

  const flush = () => {
    for (let i = 0; i < Math.max(removed.length, added.length); i++) {
      const l = removed[i];
      const r = added[i];
      rows.push({
        kind: l && r ? "change" : l ? "remove" : "add",
        left: l?.text ?? null,
        right: r?.text ?? null,
        leftNo: l?.leftNo ?? null,
        rightNo: r?.rightNo ?? null,
        leftSegments: l?.segments,
        rightSegments: r?.segments,
      });
    }
    removed = [];
    added = [];
  };

  for (const line of lines) {
    if (line.kind === "remove") {
      removed.push(line);
      continue;
    }
    if (line.kind === "add") {
      added.push(line);
      continue;
    }
    flush();
    if (line.kind === "hunk") {
      rows.push({ kind: "hunk", header: line.header });
      continue;
    }
    rows.push({
      kind: "context",
      left: line.text,
      right: line.text,
      leftNo: line.leftNo,
      rightNo: line.rightNo,
    });
  }
  flush();
  return rows;
}
