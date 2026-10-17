/**
 * Fragments that differ inside a paired changed line. Word granularity, not
 * character: `134` -> `141` highlights the whole number, and character diffs
 * of HTML read worse than no highlighting.
 */

export interface Segment {
  text: string;
  /** `true` = fragment present only on this side. */
  changed: boolean;
}

export interface IntralineDiff {
  left: Segment[];
  right: Segment[];
}

/** Words, whitespace runs and single symbols (`<`, `/`, `"`, ...). */
const TOKEN = /\s+|[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu;

/**
 * Above this threshold we give up: the LCS table is O(n*m) and a minified
 * one-liner can have thousands of tokens. 300x300 is still microseconds,
 * 5000x5000 would freeze the render thread.
 */
const MAX_TOKENS = 300;

/**
 * Below this share of common tokens the lines are treated as unrelated (the
 * whole content was replaced). An "everything changed" highlight is noise,
 * so the plain line background is better.
 */
const MIN_SIMILARITY = 0.25;

export function intralineDiff(left: string, right: string): IntralineDiff | null {
  if (left === right) return null;
  const a = left.match(TOKEN) ?? [];
  const b = right.match(TOKEN) ?? [];
  if (a.length === 0 || b.length === 0) return null;
  if (a.length > MAX_TOKENS || b.length > MAX_TOKENS) return null;

  const common = lcs(a, b);
  // Similarity ignores whitespace: spaces always match each other, so two
  // completely different lines with a similar word count would come out as
  // "half shared" and get highlighted along their whole length.
  const words = (t: string[]) => t.filter((x) => !isBlank(x)).length;
  const denominator = Math.max(words(a), words(b));
  if (denominator === 0) return null;
  if (words(common) / denominator < MIN_SIMILARITY) return null;

  return {
    left: trimEdges(merge(mark(a, common))),
    right: trimEdges(merge(mark(b, common))),
  };
}

/** Longest common subsequence of tokens (classic DP). */
function lcs(a: string[], b: string[]): string[] {
  const n = a.length;
  const m = b.length;
  // (n+1)x(m+1) common-prefix lengths.
  // Zero-initialised typed rows: no per-cell fill, half the memory of number[].
  const table = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    const row = table[i];
    const below = table[i + 1];
    if (!row || !below) continue;
    const ai = a[i];
    for (let j = m - 1; j >= 0; j--) {
      row[j] = ai === b[j] ? (below[j + 1] ?? 0) + 1 : Math.max(below[j] ?? 0, row[j + 1] ?? 0);
    }
  }
  const out: string[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    const ai = a[i];
    if (ai !== undefined && ai === b[j]) {
      out.push(ai);
      i++;
      j++;
    } else if ((table[i + 1]?.[j] ?? 0) >= (table[i]?.[j + 1] ?? 0)) {
      i++;
    } else {
      j++;
    }
  }
  return out;
}

function isBlank(token: string): boolean {
  return token.trim() === "";
}

/** Tokens outside the common subsequence are changed; adjacent ones merge
 * into one segment so the renderer does not emit a span per token. */
function mark(tokens: string[], common: string[]): Segment[] {
  const segments: Segment[] = [];
  let c = 0;
  for (const token of tokens) {
    const isCommon = c < common.length && token === common[c];
    if (isCommon) c++;
    const last = segments[segments.length - 1];
    if (last && last.changed === !isCommon) {
      last.text += token;
    } else {
      segments.push({ text: token, changed: !isCommon });
    }
  }
  return segments;
}

/**
 * Joins highlight islands separated only by a space. A space always matches
 * a space, so a changed two-word phrase would come out of `mark` as two
 * highlights with an unmarked gap: visually three blobs instead of one.
 */
function merge(segments: Segment[]): Segment[] {
  const out: Segment[] = [];
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    if (!seg) continue;
    const prev = out[out.length - 1];
    const next = segments[i + 1];
    const bridging =
      !seg.changed && isBlank(seg.text) && prev?.changed === true && next?.changed === true;
    if (prev && (prev.changed === seg.changed || bridging)) {
      prev.text += seg.text;
    } else {
      out.push({ ...seg });
    }
  }
  return out;
}

/**
 * Pushes whitespace from the edges of a highlight into its neighbours. LCS
 * can match spaces "out of order", leaving a highlight that ends with a
 * dangling gap: it looks like a marked empty character and adds nothing.
 */
function trimEdges(segments: Segment[]): Segment[] {
  const out: Segment[] = [];
  const push = (text: string, changed: boolean) => {
    if (!text) return;
    const last = out[out.length - 1];
    if (last && last.changed === changed) last.text += text;
    else out.push({ text, changed });
  };
  for (const seg of segments) {
    if (!seg.changed) {
      push(seg.text, false);
      continue;
    }
    const core = seg.text.trim();
    if (core === "") {
      // The change is whitespace only; keep it marked, otherwise a removed
      // indent would vanish from the view without a trace.
      push(seg.text, true);
      continue;
    }
    const start = seg.text.indexOf(core);
    push(seg.text.slice(0, start), false);
    push(core, true);
    push(seg.text.slice(start + core.length), false);
  }
  return out;
}
