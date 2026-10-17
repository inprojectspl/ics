/**
 * Activate interactive widgets in the hydrated markdown DOM.
 * Each widget family is lazy-imported only when needed and cached at module
 * scope so theme toggles don't re-download libraries.
 */

import type { HighlighterCore } from "shiki/core";
import { ICON_SVG } from "./calloutIcons";
import { t } from "./i18n";
import { mountMermaid, repaintMermaid } from "./mermaid";

let shikiPromise: Promise<HighlighterCore> | null = null;

async function mountKaTeX(root: HTMLElement): Promise<void> {
  const nodes = root.querySelectorAll<HTMLElement>(".math[data-widget^='math']");
  if (nodes.length === 0) return;

  const [{ default: katex }] = await Promise.all([
    import("katex"),
    import("katex/dist/katex.min.css"),
  ]);

  for (const node of nodes) {
    if (node.dataset.rendered === "1") continue;
    const tex = (node.textContent || "").trim();
    const displayMode = node.dataset.widget === "math-block";
    try {
      katex.render(tex, node, { throwOnError: false, displayMode, output: "html" });
      node.dataset.rendered = "1";
    } catch {
      /* throwOnError:false already inlines error */
    }
  }
}

// Fine-grained imports: the full `shiki` bundle ships ~300 grammars and the
// Oniguruma wasm, while only these languages are highlighted. The JavaScript
// regex engine avoids the wasm download altogether.
async function getHighlighter(): Promise<HighlighterCore> {
  if (shikiPromise) return shikiPromise;
  shikiPromise = (async () => {
    const [{ createHighlighterCore }, { createJavaScriptRegexEngine }] = await Promise.all([
      import("shiki/core"),
      import("shiki/engine/javascript"),
    ]);
    return createHighlighterCore({
      engine: createJavaScriptRegexEngine(),
      themes: [import("shiki/themes/github-light.mjs"), import("shiki/themes/github-dark.mjs")],
      langs: [
        import("shiki/langs/javascript.mjs"),
        import("shiki/langs/typescript.mjs"),
        import("shiki/langs/tsx.mjs"),
        import("shiki/langs/jsx.mjs"),
        import("shiki/langs/json.mjs"),
        import("shiki/langs/python.mjs"),
        import("shiki/langs/go.mjs"),
        import("shiki/langs/rust.mjs"),
        // Also registers the `bash`, `sh` and `shell` aliases.
        import("shiki/langs/shellscript.mjs"),
        import("shiki/langs/yaml.mjs"),
        import("shiki/langs/toml.mjs"),
        import("shiki/langs/css.mjs"),
        import("shiki/langs/html.mjs"),
        import("shiki/langs/sql.mjs"),
        import("shiki/langs/diff.mjs"),
        import("shiki/langs/markdown.mjs"),
        // Also registers `dockerfile`.
        import("shiki/langs/docker.mjs"),
        import("shiki/langs/ini.mjs"),
      ],
    });
  })();
  return shikiPromise;
}

async function mountShiki(root: HTMLElement, theme: "light" | "dark"): Promise<void> {
  const blocks = root.querySelectorAll<HTMLElement>(".code-figure pre[data-widget='code']");
  if (blocks.length === 0) return;

  const highlighter = await getHighlighter();
  const themeName = theme === "dark" ? "github-dark" : "github-light";

  blocks.forEach((pre) => {
    const code = pre.querySelector("code");
    const text = code?.textContent || "";
    const lang = (pre.dataset.lang || "txt").toLowerCase();
    try {
      const html = highlighter.codeToHtml(text, {
        lang: highlighter.getLoadedLanguages().includes(lang as never) ? (lang as never) : "txt",
        theme: themeName,
      });
      const tmp = document.createElement("div");
      tmp.innerHTML = html;
      const newCode = tmp.querySelector("code");
      if (newCode && code) {
        code.replaceWith(newCode);
      }
      pre.dataset.shiki = "1";
      pre.style.background = "transparent";
    } catch {
      /* leave as plain code */
    }
  });
}

function mountCopyButtons(root: HTMLElement): void {
  root.querySelectorAll<HTMLButtonElement>("button.code-copy").forEach((btn) => {
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", async () => {
      const code = btn.closest(".code-figure")?.querySelector("code");
      const text = code?.textContent || "";
      try {
        await navigator.clipboard.writeText(text);
        const original = btn.textContent;
        btn.textContent = t("markdown.copied");
        btn.setAttribute("aria-live", "polite");
        setTimeout(() => {
          btn.textContent = original;
        }, 1500);
      } catch {
        btn.textContent = t("markdown.copyFailed");
      }
    });
  });
}

function mountCalloutIcons(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>(".callout-icon[data-lucide]").forEach((slot) => {
    if (slot.dataset.rendered === "1") return;
    const name = slot.dataset.lucide || "info";
    slot.innerHTML = ICON_SVG[name] || ICON_SVG.info || "";
    slot.dataset.rendered = "1";
  });
}

export interface MountOptions {
  theme: "light" | "dark";
}

/** Initial mount: bind copy buttons + icons + run heavy widgets. */
export async function mountWidgets(root: HTMLElement, opts: MountOptions): Promise<void> {
  mountCalloutIcons(root);
  mountCopyButtons(root);
  mountMermaid(root, opts.theme); // sync: registers the lazy observers
  await Promise.all([
    mountKaTeX(root),
    mountShiki(root, opts.theme),
  ]);
}

/** Re-skin only - call when theme changes without re-parsing the DOM. */
export async function repaintForTheme(root: HTMLElement, theme: "light" | "dark"): Promise<void> {
  // Clear shiki marker so blocks re-paint with new theme.
  root.querySelectorAll<HTMLElement>(".code-figure pre[data-shiki='1']").forEach((pre) => {
    delete pre.dataset.shiki;
  });
  // Mermaid: re-render rendered figures from cached source (hidden <pre>).
  await Promise.all([mountShiki(root, theme), repaintMermaid(root, theme)]);
}
