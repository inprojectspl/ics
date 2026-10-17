import { describe, expect, it } from "vitest";

import {
  agentViewHref,
  buildMcpCall,
  effectiveFormat,
  isMultiFile,
  readableFiles,
} from "./agentView";

describe("agent view helpers", () => {
  it("reads HTML as Markdown by default and other files without a format", () => {
    expect(effectiveFormat("index.html", undefined)).toBe("markdown");
    expect(effectiveFormat("PAGE.HTM", "raw")).toBe("raw");
    expect(effectiveFormat("notes.md", "raw")).toBeUndefined();
    expect(effectiveFormat(null, "markdown")).toBeUndefined();
  });

  it("builds the ics_asset_read call an agent would make", () => {
    expect(buildMcpCall("abc", {})).toBe('ics_asset_read(slug_or_id="abc")');
    expect(buildMcpCall("abc", { path: "index.html", format: "markdown", version: 2 })).toBe(
      'ics_asset_read(slug_or_id="abc", path="index.html", format="markdown", version=2)',
    );
  });

  it("keeps the address short for the default read", () => {
    expect(agentViewHref("abc", {})).toBe("/v/abc/agent");
    expect(agentViewHref("abc", { path: "a b.md", format: "raw", version: 3 })).toBe(
      "/v/abc/agent?p=a+b.md&fmt=raw&ver=3",
    );
  });

  it("leaves binary files out of the picker", () => {
    expect(readableFiles(["index.html", "logo.PNG", "font.woff2", "app.css", "doc.pdf"])).toEqual([
      "index.html",
      "app.css",
    ]);
  });

  it("tells multi-file kinds apart", () => {
    expect(isMultiFile("html_bundle")).toBe(true);
    expect(isMultiFile("md_collection")).toBe(true);
    expect(isMultiFile("pdf_doc")).toBe(false);
  });
});
