import { describe, it, expect } from "vitest";
import { MD_BREAKOUT } from "../styles/markdown-theme";
import { hydrateMarkdown } from "./hydrateMarkdown";

function mount(html: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = html;
  document.body.appendChild(root);
  hydrateMarkdown(root);
  return root;
}

describe("hydrateMarkdown: the .md-breakout marker", () => {
  it("plain table: wrapper without .md-breakout (stays in the text column)", () => {
    const root = mount(`
      <table><thead><tr><th>A</th><th>B</th></tr></thead>
        <tbody><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></tbody>
      </table>
    `);
    const wrap = root.querySelector(".table-wrap");
    expect(wrap).not.toBeNull();
    // Tables stay within the column; breakout is reserved for code/video/mermaid.
    expect(wrap?.classList.contains(MD_BREAKOUT)).toBe(false);
  });

  it("kv-table: wrapper without .md-breakout (stays in the column)", () => {
    const root = mount(`
      <table><tbody>
        <tr><td><strong>Field</strong></td><td>value</td></tr>
        <tr><td><strong>Other</strong></td><td>value 2</td></tr>
      </tbody></table>
    `);
    expect(root.querySelector("table")?.classList.contains("kv-table")).toBe(true);
    const wrap = root.querySelector(".table-wrap");
    expect(wrap?.classList.contains(MD_BREAKOUT)).toBe(false);
  });

  it("code block: code-figure gets .md-breakout", () => {
    const root = mount(`<pre data-widget="code" data-lang="ts"><code>const x = 1;</code></pre>`);
    const figure = root.querySelector(".code-figure");
    expect(figure?.classList.contains(MD_BREAKOUT)).toBe(true);
  });

  it("video (iframe and native): the wrapper gets .md-breakout", () => {
    const root = mount(`<iframe src="https://example.com/embed"></iframe><video src="x.mp4"></video>`);
    const wraps = root.querySelectorAll(".video-wrap");
    expect(wraps.length).toBe(2);
    wraps.forEach((w) => expect(w.classList.contains(MD_BREAKOUT)).toBe(true));
  });

  it("mermaid: the figure gets .md-breakout", () => {
    const root = mount(`<pre class="mermaid" data-widget="mermaid">graph TD; A--&gt;B</pre>`);
    const figure = root.querySelector("figure.mermaid-figure");
    expect(figure?.classList.contains(MD_BREAKOUT)).toBe(true);
  });
});

describe("decorateMermaid: anti-overflow / anti-CLS scaffold", () => {
  it("wraps <pre> in a figure with a viewport and hides the raw source", () => {
    const root = mount(`<pre class="mermaid" data-widget="mermaid">graph TD; A--&gt;B; C--&gt;D</pre>`);
    const figure = root.querySelector("figure.mermaid-figure");
    expect(figure).not.toBeNull();
    const viewport = figure?.querySelector(".mermaid-viewport");
    expect(viewport).not.toBeNull();
    // The raw <pre> stays as a hidden source carrier (for render and repaint).
    const pre = viewport?.querySelector<HTMLElement>("pre.mermaid");
    expect(pre?.hidden).toBe(true);
    expect((pre?.textContent || "").includes("graph TD")).toBe(true);
    // The skeleton stays visible until the SVG renders.
    expect(figure?.querySelector(".mermaid-skeleton")).not.toBeNull();
  });

  it("is idempotent: a second pass creates no nested figure", () => {
    const root = mount(`<pre class="mermaid" data-widget="mermaid">graph TD; A--&gt;B</pre>`);
    hydrateMarkdown(root); // second pass
    expect(root.querySelectorAll("figure.mermaid-figure").length).toBe(1);
  });
});

describe("hydrateMarkdown: kv-table detection", () => {
  it("enables .kv-table for a table with the | **Label** | value | pattern", () => {
    // Backend HTML shape of a 'Field | Value' table
    const root = mount(`
      <table>
        <thead><tr><th>Field</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td><strong>Reference number</strong></td><td>10000001</td></tr>
          <tr><td><strong>Public notice</strong></td><td><a href="x">000001-2026</a></td></tr>
          <tr><td><strong>Procedure</strong></td><td>Open procedure, section 18(1)</td></tr>
        </tbody>
      </table>
    `);
    expect(root.querySelector("table")?.classList.contains("kv-table")).toBe(true);
  });

  it("does not enable it for a numbered | 1 | text | table (no <strong>)", () => {
    // Backend HTML shape of a numbered scope table
    const root = mount(`
      <table>
        <thead><tr><th>Iteration</th><th>Scope</th></tr></thead>
        <tbody>
          <tr><td>1</td><td>Technical analysis of 12 repositories</td></tr>
          <tr><td>2</td><td>Business context (requirements, regulator guidelines)</td></tr>
          <tr><td>3</td><td>Legal layer (statute, mapping onto code)</td></tr>
        </tbody>
      </table>
    `);
    expect(root.querySelector("table")?.classList.contains("kv-table")).toBe(false);
  });

  it("does not enable it for a 3-column table with a bold prefix", () => {
    const root = mount(`
      <table>
        <thead><tr><th>Name</th><th>Email</th><th>Role</th></tr></thead>
        <tbody>
          <tr><td><strong>Alice</strong></td><td>alice@example.com</td><td>admin</td></tr>
          <tr><td><strong>Bob</strong></td><td>bob@example.com</td><td>editor</td></tr>
        </tbody>
      </table>
    `);
    expect(root.querySelector("table")?.classList.contains("kv-table")).toBe(false);
  });

  it("does not enable it when only some rows have <strong>", () => {
    const root = mount(`
      <table>
        <thead><tr><th>Field</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td><strong>Label A</strong></td><td>val A</td></tr>
          <tr><td>Label B</td><td>val B</td></tr>
        </tbody>
      </table>
    `);
    expect(root.querySelector("table")?.classList.contains("kv-table")).toBe(false);
  });

  it("does not enable it when <strong> covers under 70% of the text (emphasis mid-sentence)", () => {
    const root = mount(`
      <table>
        <thead><tr><th>Field</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td>plain text with <strong>emphasis</strong> in the middle of a sentence</td><td>val</td></tr>
          <tr><td>more text with <strong>emphasis</strong> inside</td><td>val</td></tr>
        </tbody>
      </table>
    `);
    expect(root.querySelector("table")?.classList.contains("kv-table")).toBe(false);
  });

  it("does not enable it for a single row", () => {
    const root = mount(`
      <table>
        <thead><tr><th>Field</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td><strong>Reference</strong></td><td>10000001</td></tr>
        </tbody>
      </table>
    `);
    expect(root.querySelector("table")?.classList.contains("kv-table")).toBe(false);
  });

  it("works without thead (e.g. a Markdown table without a header)", () => {
    const root = mount(`
      <table>
        <tbody>
          <tr><td><strong>Region</strong></td><td>Region A lot 2 + Region B lot 11</td></tr>
          <tr><td><strong>Output</strong></td><td>a 'no-go' list before the 2026-Q3 contract signing</td></tr>
        </tbody>
      </table>
    `);
    expect(root.querySelector("table")?.classList.contains("kv-table")).toBe(true);
  });

  it("ignores colspans (different td.length per row)", () => {
    const root = mount(`
      <table>
        <thead><tr><th colspan="2">Header</th></tr></thead>
        <tbody>
          <tr><td colspan="2">Full row</td></tr>
          <tr><td><strong>Label</strong></td><td>val</td></tr>
        </tbody>
      </table>
    `);
    expect(root.querySelector("table")?.classList.contains("kv-table")).toBe(false);
  });
});

describe("hydrateMarkdown: table wrap", () => {
  it("wraps the table in .table-wrap", () => {
    const root = mount(`<table><tbody><tr><td>a</td><td>b</td></tr></tbody></table>`);
    const wrap = root.querySelector(".table-wrap");
    expect(wrap).not.toBeNull();
    expect(wrap?.querySelector("table")).not.toBeNull();
  });

  it("is idempotent: a second call does not double the wrapper", () => {
    const root = document.createElement("div");
    root.innerHTML = `<table><tbody><tr><td>a</td><td>b</td></tr></tbody></table>`;
    document.body.appendChild(root);
    hydrateMarkdown(root);
    hydrateMarkdown(root);
    expect(root.querySelectorAll(".table-wrap").length).toBe(1);
  });
});

describe("hydrateMarkdown - wikilink href", () => {
  const ctx = {
    paths: ["notes/Page.md"],
    current: "index.md",
    hrefFor: (p: string) => `/a/slug/${p}`,
  };

  function mountWith(target: string): HTMLAnchorElement {
    const root = document.createElement("div");
    const a = document.createElement("a");
    a.className = "wikilink";
    a.dataset.target = target;
    root.appendChild(a);
    hydrateMarkdown(root, ctx);
    return a;
  }

  it("sets href only for a target resolved to a known collection path", () => {
    expect(mountWith("Page").getAttribute("href")).toBe("/a/slug/notes/Page.md");
  });

  it.each(["javascript:alert(1)", "https://evil.example/", "//evil.example", "data:text/html,x"])(
    "never turns data-target %s into an href",
    (target) => {
      expect(mountWith(target).hasAttribute("href")).toBe(false);
    },
  );
});
