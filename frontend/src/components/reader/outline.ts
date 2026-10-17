export interface OutlineEntry {
  id: string;
  text: string;
  level: 2 | 3;
}

/** Sections of a rendered document for its table of contents: the h2 and
 * h3 that carry an anchor (hydrateMarkdown gives every heading an id). The
 * h1 is the document title and stays out. */
export function readOutline(root: HTMLElement): OutlineEntry[] {
  const out: OutlineEntry[] = [];
  for (const h of root.querySelectorAll<HTMLHeadingElement>("h2[id], h3[id]")) {
    // The anchor link's glyph is part of textContent; take the heading's own text.
    const text = [...h.childNodes]
      .filter((n) => !(n instanceof HTMLElement && n.classList.contains("heading-anchor")))
      .map((n) => n.textContent ?? "")
      .join("")
      .trim();
    if (text) out.push({ id: h.id, text, level: h.tagName === "H2" ? 2 : 3 });
  }
  return out;
}
