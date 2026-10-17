/**
 * Text helpers of the card renderer. Measuring is the costly part of a frame,
 * so results are cached by font, width and text; callers that scale text with
 * the zoom measure at a fixed reference size (`REF_SIZE`) to keep hitting it.
 */
export const FONT = '"Mona Sans", ui-sans-serif, system-ui, sans-serif';
/** Font size text is measured at when its drawn size follows the zoom. */
export const REF_SIZE = 12;

const CACHE_LIMIT = 6000;
const truncCache = new Map<string, string>();
const wrapCache = new Map<string, string[]>();

/** `text` cut with an ellipsis to fit `max` in the context's current font. */
export function fitText(ctx: CanvasRenderingContext2D, text: string, max: number): string {
  const key = `${ctx.font}\u0000${Math.round(max)}\u0000${text}`;
  const hit = truncCache.get(key);
  if (hit !== undefined) return hit;
  let out = text;
  if (max <= 0) out = "";
  else if (ctx.measureText(text).width > max) {
    let lo = 0;
    let hi = text.length;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (ctx.measureText(text.slice(0, mid).trimEnd() + "…").width <= max) lo = mid;
      else hi = mid - 1;
    }
    out = lo > 0 ? text.slice(0, lo).trimEnd() + "…" : "";
  }
  if (truncCache.size > CACHE_LIMIT) truncCache.clear();
  truncCache.set(key, out);
  return out;
}

/**
 * Text on up to `lines` lines: whole words on every line but the last, the
 * rest cut with an ellipsis on the last one.
 */
export function wrapLines(ctx: CanvasRenderingContext2D, text: string, max: number, lines = 2): string[] {
  const key = `${ctx.font}\u0000${Math.round(max)}\u0000${lines}\u0000${text}`;
  const hit = wrapCache.get(key);
  if (hit) return hit;
  const out = split(ctx, text, max, lines);
  if (wrapCache.size > CACHE_LIMIT) wrapCache.clear();
  wrapCache.set(key, out);
  return out;
}

/** Whether `lines` came out of `wrapLines` cut, not whole. */
export const isCut = (lines: string[]): boolean => lines[lines.length - 1]?.endsWith("…") ?? false;

function split(ctx: CanvasRenderingContext2D, text: string, max: number, lines: number): string[] {
  if (ctx.measureText(text).width <= max) return [text];
  if (lines <= 1) return [fitText(ctx, text, max)];
  const words = text.split(/\s+/);
  let first = "";
  let used = 0;
  for (const [i, w] of words.entries()) {
    const next = first ? `${first} ${w}` : w;
    if (ctx.measureText(next).width > max) break;
    first = next;
    used = i + 1;
  }
  if (used === 0) return [fitText(ctx, text, max)];
  return [first, ...split(ctx, words.slice(used).join(" "), max, lines - 1)];
}

export function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}
