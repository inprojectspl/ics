import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("./PdfReader", () => ({
  PdfReader: ({ url }: { url: string }) => <div data-testid="pdf-view">{url}</div>,
}));

const { PdfDocument } = await import("./index");

describe("PdfDocument", () => {
  it("lazy-loads the page renderer with the PDF URL and offers the download", async () => {
    render(
      <PdfDocument
        url="/api/assets/by-slug/s/pdf"
        title="Contract"
        meta="12 May 2026"
        info={{ page_count: 4, text_page_count: 4 }}
        downloadHref="/api/assets/by-slug/s/download"
      />,
    );
    expect(await screen.findByTestId("pdf-view")).toHaveTextContent("/api/assets/by-slug/s/pdf");
    expect(screen.getByRole("heading", { name: "Contract" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download PDF" })).toHaveAttribute(
      "href",
      "/api/assets/by-slug/s/download",
    );
    expect(screen.queryByText(/text layer/)).not.toBeInTheDocument();
  });

  it("warns that a scanned PDF has no searchable text", async () => {
    render(<PdfDocument url="/x.pdf" title={null} info={{ page_count: 3, text_page_count: 0 }} />);
    expect(screen.getByText(/has no text layer/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    await screen.findByTestId("pdf-view");
  });

  it("shows the OCR state of a scan instead of the plain note", async () => {
    render(
      <PdfDocument
        url="/x.pdf"
        title={null}
        info={{ page_count: 3, text_page_count: 0 }}
        ocr={<p>OCR slot</p>}
      />,
    );
    expect(screen.getByText("OCR slot")).toBeInTheDocument();
    expect(screen.queryByText(/search will not find/)).not.toBeInTheDocument();
    await screen.findByTestId("pdf-view");
  });

  it("shows security findings to the owner", async () => {
    render(
      <PdfDocument
        url="/x.pdf"
        title="Doc"
        securityStatus="warn"
        securityReport={{
          status: "warn",
          findings: [
            { severity: "warn", rule: "pdf_javascript", file: "doc.pdf", line: null, message: "JS" },
          ],
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("pdf_javascript");
    await screen.findByTestId("pdf-view");
  });

  it("withholds the pages and the download from a visitor while under review", () => {
    render(
      <PdfDocument url="/x.pdf" title="Doc" downloadHref="/dl" accessGated />,
    );
    expect(screen.getByText("On hold")).toBeInTheDocument();
    expect(screen.queryByTestId("pdf-view")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
