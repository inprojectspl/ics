import { api } from "../api";

const SELECTOR = "a.wikilink-ics[data-ics-slug]";
// Matches MAX_LINK_SLUGS on the server.
const MAX_SLUGS = 100;

/**
 * Replace the slug text of `[[ics:...]]` links with the target's title. The
 * cached HTML carries only slugs because titles depend on the viewer and can
 * change without a new version (ADR-0006 addendum); targets the viewer cannot
 * see, and every link for a visitor without a session, keep the slug.
 */
export async function fillIcsLinkTitles(root: HTMLElement, isStale: () => boolean): Promise<void> {
  const links = Array.from(root.querySelectorAll<HTMLAnchorElement>(SELECTOR));
  const slugs = [...new Set(links.map((a) => a.dataset.icsSlug ?? ""))].filter(Boolean);
  if (slugs.length === 0) return;
  let titles: Record<string, string>;
  try {
    titles = await api.linkTitles(slugs.slice(0, MAX_SLUGS));
  } catch {
    return;
  }
  if (isStale()) return;
  for (const a of links) {
    const slug = a.dataset.icsSlug ?? "";
    const title = titles[slug];
    const text = a.textContent ?? "";
    // `slug` or `slug/path`; anything else was changed after rendering.
    if (!title || (text !== slug && !text.startsWith(`${slug}/`))) continue;
    a.textContent = title + (text === slug ? "" : ` / ${text.slice(slug.length + 1)}`);
    a.title = text;
  }
}
