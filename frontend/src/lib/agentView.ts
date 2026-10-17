// Pure helpers of the agent view (`views/AgentView.tsx`).

import type { AgentFormat, AgentReadOpts, AssetKind } from "../api";

export type { AgentFormat, AgentReadOpts };
export type AgentViewMode = "rendered" | "source";

/** Kinds whose files an agent picks by `path`; the others are one file. */
export function isMultiFile(kind: AssetKind): boolean {
  return kind === "md_collection" || kind === "html_bundle";
}

export function isHtmlPath(path: string | null | undefined): boolean {
  return Boolean(path && /\.html?$/i.test(path));
}

// Files an agent cannot read as text (file-mcp answers 415). The picker
// leaves them out; nothing useful would show for them.
const BINARY_EXT =
  /\.(png|jpe?g|gif|webp|avif|bmp|ico|tiff?|woff2?|ttf|otf|eot|pdf|zip|gz|mp3|mp4|webm|ogg|wav|mov)$/i;

export function readableFiles(paths: string[]): string[] {
  return paths.filter((p) => !BINARY_EXT.test(p));
}

/** The `format` an agent passes for this file: HTML reads as Markdown unless
 * the raw source is picked; other files take no `format`. */
export function effectiveFormat(
  path: string | null | undefined,
  requested: AgentFormat | undefined,
): AgentFormat | undefined {
  return isHtmlPath(path) ? (requested ?? "markdown") : undefined;
}

/** The `ics_asset_read` call that returns this content, for copying into a
 * prompt or a bug report. */
export function buildMcpCall(slug: string, opts: AgentReadOpts): string {
  const args = [`slug_or_id="${slug}"`];
  if (opts.path) args.push(`path="${opts.path}"`);
  if (opts.format) args.push(`format="${opts.format}"`);
  if (opts.version) args.push(`version=${opts.version}`);
  return `ics_asset_read(${args.join(", ")})`;
}

/** Address of the agent view with the given choices, `null`/absent values
 * dropped so the default reads stay short. */
export function agentViewHref(slug: string, opts: AgentReadOpts): string {
  const q = new URLSearchParams();
  if (opts.path) q.set("p", opts.path);
  if (opts.format) q.set("fmt", opts.format);
  if (opts.version) q.set("ver", String(opts.version));
  const qs = q.toString();
  return `/v/${slug}/agent${qs ? `?${qs}` : ""}`;
}
