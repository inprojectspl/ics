import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Shiki and mermaid are not needed for plain paragraphs; the stub keeps the
// test free of dynamic imports settling after unmount.
vi.mock("../../lib/mountWidgets", () => ({
  mountWidgets: vi.fn(async () => {}),
  repaintForTheme: vi.fn(async () => {}),
}));

const { OfficeDocument } = await import("./index");

const html = "<h2>Field guide</h2><p>Second paragraph about wombats</p>";

describe("OfficeDocument", () => {
  it("renders the converted body with the title and the original download", () => {
    render(
      <OfficeDocument
        html={html}
        theme="light"
        title="Guide"
        meta="12 May 2026"
        info={{ source_format: "docx", images: 0 }}
        downloadHref="/api/assets/by-slug/g/download"
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Guide" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: /Field guide/ })).toBeInTheDocument();
    expect(screen.getByText("Second paragraph about wombats")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download original" })).toHaveAttribute(
      "href",
      "/api/assets/by-slug/g/download",
    );
  });

  it.each([
    ["docx", ".docx"],
    ["odt", ".odt"],
    ["doc", ".doc"],
  ] as const)("names the %s source format in the converted-preview note", (format, ext) => {
    render(
      <OfficeDocument html={html} theme="light" title="Doc" info={{ source_format: format, images: 0 }} />,
    );
    expect(screen.getByText(/converted from a/)).toHaveTextContent(`from a ${ext} file.`);
  });

  it("mentions skipped images only when the document had some", () => {
    const { rerender } = render(
      <OfficeDocument html={html} theme="light" title="Doc" info={{ source_format: "odt", images: 0 }} />,
    );
    expect(screen.queryByText(/image/)).not.toBeInTheDocument();

    rerender(
      <OfficeDocument html={html} theme="light" title="Doc" info={{ source_format: "odt", images: 3 }} />,
    );
    expect(screen.getByText(/has 3 images/)).toBeInTheDocument();
  });

  it("renders without notes or download when the payload has no document info", () => {
    render(<OfficeDocument html={html} theme="dark" title={null} />);
    expect(screen.getByText("Second paragraph about wombats")).toBeInTheDocument();
    expect(screen.queryByText(/converted from/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Download original" })).not.toBeInTheDocument();
  });

  it("shows security findings to the owner", () => {
    render(
      <OfficeDocument
        html={html}
        theme="light"
        title="Doc"
        securityStatus="critical"
        securityReport={{
          status: "critical",
          findings: [
            { severity: "critical", rule: "office_macros", file: "a.docx", line: null, message: "M" },
          ],
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("office_macros");
    expect(screen.getByText("Second paragraph about wombats")).toBeInTheDocument();
  });

  it("withholds the text and the download from a visitor while under review", () => {
    render(
      <OfficeDocument
        html={html}
        theme="light"
        title="Doc"
        info={{ source_format: "docx", images: 2 }}
        downloadHref="/dl"
        accessGated
      />,
    );
    expect(screen.getByText("On hold")).toBeInTheDocument();
    expect(screen.queryByText("Second paragraph about wombats")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText(/image/)).not.toBeInTheDocument();
  });
});
