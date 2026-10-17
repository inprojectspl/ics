/** Address of the graph view, centred on one document when `slug` is given. */
export function graphHref(slug?: string): string {
  return slug ? `/graph?doc=${encodeURIComponent(slug)}` : "/graph";
}
