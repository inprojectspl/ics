import { beforeEach, describe, expect, it, vi } from "vitest";

import { fillIcsLinkTitles } from "./icsLinkTitles";

const linkTitles = vi.fn();
vi.mock("../api", () => ({ api: { linkTitles: (...a: unknown[]) => linkTitles(...a) } }));

function root(html: string): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = html;
  return el;
}

const link = (slug: string, text: string) =>
  `<a class="wikilink wikilink-ics" href="/v/${slug}" data-ics-slug="${slug}">${text}</a>`;

beforeEach(() => {
  linkTitles.mockReset();
});

describe("fillIcsLinkTitles", () => {
  it("shows visible titles and keeps the slug of the rest", async () => {
    linkTitles.mockResolvedValue({ abc: "API specification" });
    const el = root(
      link("abc", "abc") + link("abc", "abc/spec.md") + link("hid", "hid") +
        '<a class="wikilink wikilink-ics" href="/v/abc">Alias</a>',
    );
    await fillIcsLinkTitles(el, () => false);

    expect(linkTitles).toHaveBeenCalledWith(["abc", "hid"]);
    const texts = Array.from(el.querySelectorAll("a")).map((a) => a.textContent);
    expect(texts).toEqual(["API specification", "API specification / spec.md", "hid", "Alias"]);
    expect(el.querySelector("a")?.getAttribute("title")).toBe("abc");
  });

  it("does not call the API without ics links", async () => {
    await fillIcsLinkTitles(root("<p>plain</p>"), () => false);
    expect(linkTitles).not.toHaveBeenCalled();
  });

  it("keeps slugs when the request fails or the view changed", async () => {
    linkTitles.mockRejectedValueOnce(new Error("401"));
    const el = root(link("abc", "abc"));
    await fillIcsLinkTitles(el, () => false);
    expect(el.textContent).toBe("abc");

    linkTitles.mockResolvedValueOnce({ abc: "Title" });
    await fillIcsLinkTitles(el, () => true);
    expect(el.textContent).toBe("abc");
  });
});
