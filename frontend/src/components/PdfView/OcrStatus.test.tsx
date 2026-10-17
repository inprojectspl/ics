import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OcrState } from "../../api";
import { ApiError } from "../../api/_core";
import { qk } from "../../lib/queries";
import { renderWithClient } from "../../test-utils";
import { failureReason } from "../../lib/ocr";
import { LiveOcrStatus, OcrStatusView } from "./OcrStatus";

const getOcr = vi.fn();
const requestOcr = vi.fn();

vi.mock("../../api", () => ({
  api: {
    getOcr: (...a: unknown[]) => getOcr(...a),
    requestOcr: (...a: unknown[]) => requestOcr(...a),
  },
}));

function state(over: Partial<OcrState> = {}): OcrState {
  return {
    status: "not_requested",
    pages_without_text: 2,
    pages_with_hidden_text: 0,
    available: true,
    provider: null,
    requested_at: null,
    started_at: null,
    finished_at: null,
    pages_total: null,
    pages_done: null,
    pages_recognized: null,
    error_code: null,
    providers: [{ name: "local", needs_api_key: false }],
    ...over,
  };
}

beforeEach(() => {
  getOcr.mockReset();
  requestOcr.mockReset();
});

describe("OcrStatusView", () => {
  it("renders nothing for a PDF whose pages all have text", () => {
    const { container } = render(<OcrStatusView state={state({ pages_without_text: 0 })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("offers the first run for a scan that was never read", () => {
    const onRequest = vi.fn();
    render(<OcrStatusView state={state()} onRequest={onRequest} />);
    expect(screen.getByText(/2 pages have no text layer/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Recognize text (OCR)" }));
    expect(onRequest).toHaveBeenCalledOnce();
  });

  it("recommends OCR for scans with a text layer saved in the file", () => {
    render(
      <OcrStatusView
        state={state({ pages_without_text: 0, pages_with_hidden_text: 247 })}
        onRequest={vi.fn()}
        textHref="/v/s/agent"
      />,
    );
    expect(screen.getByRole("link", { name: "Show text" })).toHaveAttribute("href", "/v/s/agent");
    expect(screen.getByText(/247 pages are scans with a text layer saved in the file/)).toBeInTheDocument();
    expect(screen.getByText(/OCR is recommended/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recognize text (OCR)" })).toBeInTheDocument();
  });

  it("has no action for a reader who cannot request, or when OCR is off", () => {
    const { rerender } = render(<OcrStatusView state={state()} textHref="/v/s/agent" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    // A scan without any text has nothing to show yet.
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    rerender(<OcrStatusView state={state({ available: false })} onRequest={vi.fn()} />);
    expect(screen.getByText(/OCR is turned off/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows progress while running and no retry until it ends", () => {
    render(
      <OcrStatusView
        state={state({ status: "running", pages_total: 8, pages_done: 2 })}
        onRequest={vi.fn()}
      />,
    );
    expect(screen.getByText("OCR in progress: page 2 of 8.")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("reports a finished run with its date, the text link and a retry", () => {
    render(
      <OcrStatusView
        state={state({
          status: "done",
          finished_at: "2026-09-28T08:15:00Z",
          pages_total: 7,
          pages_recognized: 6,
        })}
        onRequest={vi.fn()}
        textHref="/v/s/agent"
      />,
    );
    expect(screen.getByText(/OCR finished .*2026.*Pages read: 7, text recognized on 6\./)).toBeInTheDocument();
    expect(screen.queryByText(/The other/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Show text" })).toHaveAttribute("href", "/v/s/agent");
    expect(screen.getByRole("button", { name: "Run OCR again" })).toBeInTheDocument();
  });

  it("says a run over a few scans left the other pages alone", () => {
    const { rerender } = render(
      <OcrStatusView state={state({ status: "done", pages_total: 4, pages_recognized: 4 })} pageCount={55} />,
    );
    expect(screen.getByText(/The other 51 of 55 pages have their own text layer/)).toBeInTheDocument();
    rerender(<OcrStatusView state={state({ status: "running", pages_total: 4, pages_done: 1 })} pageCount={5} />);
    expect(
      screen.getByText("OCR in progress: page 1 of 4. The other 1 of 5 pages has its own text layer, so OCR does not read it."),
    ).toBeInTheDocument();
  });

  it("explains a failure in words", () => {
    render(
      <OcrStatusView
        state={state({ status: "failed", error_code: "ocr_timeout", finished_at: "2026-09-28T08:15:00Z" })}
        onRequest={vi.fn()}
      />,
    );
    expect(screen.getByText(/OCR failed .*time limit/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run OCR again" })).toBeInTheDocument();
  });

  it("lets the reader pick a cloud engine and asks for its key", () => {
    const onRequest = vi.fn();
    render(
      <OcrStatusView
        state={state({
          providers: [
            { name: "local", needs_api_key: false },
            { name: "mistral", needs_api_key: true },
          ],
        })}
        onRequest={onRequest}
      />,
    );
    const run = screen.getByRole("button", { name: "Recognize text (OCR)" });
    expect(screen.queryByLabelText("Mistral API key")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("OCR engine"), { target: { value: "mistral" } });
    expect(screen.getByText(/will be sent to Mistral AI/)).toBeInTheDocument();
    expect(run).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Mistral API key"), { target: { value: " sk-1 " } });
    fireEvent.click(run);
    expect(onRequest).toHaveBeenCalledWith({ provider: "mistral", api_key: "sk-1" });
  });

  it("names the engine of a finished run", () => {
    render(
      <OcrStatusView
        state={state({ status: "done", provider: "mistral", finished_at: "2026-09-28T08:15:00Z" })}
      />,
    );
    expect(screen.getByText(/\(Mistral OCR 4\)/)).toBeInTheDocument();
  });

  it("maps failure codes: OCR ones, document ones, then a generic reason", () => {
    expect(failureReason("ocr_out_of_memory")).toMatch(/memory/);
    expect(failureReason("pdf_encrypted")).toMatch(/password/);
    expect(failureReason("something_new")).toBe("unknown error.");
    expect(failureReason(null)).toBe("unknown error.");
  });
});

describe("LiveOcrStatus", () => {
  it("queues a run and shows it as queued", async () => {
    requestOcr.mockResolvedValue({ slug: "s", version: 1, ocr: state({ status: "queued" }) });
    getOcr.mockReturnValue(new Promise(() => {}));
    renderWithClient(<LiveOcrStatus slug="s" assetId="a1" initial={state()} canRequest />);
    fireEvent.click(screen.getByRole("button", { name: "Recognize text (OCR)" }));
    expect(await screen.findByText(/OCR is queued/)).toBeInTheDocument();
    expect(requestOcr).toHaveBeenCalledWith("a1", {});
  });

  it("shows why a request was refused", async () => {
    requestOcr.mockRejectedValue(new ApiError(409, "busy", "409 Conflict", "ocr_in_progress"));
    renderWithClient(
      <LiveOcrStatus slug="s" assetId="a1" initial={state({ status: "failed" })} canRequest />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Run OCR again" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already running or queued/);
  });

  it("refreshes the document once an active run ends", async () => {
    getOcr.mockResolvedValue({
      slug: "s",
      version: 1,
      ocr: state({ status: "done", pages_total: 2, pages_recognized: 2, finished_at: "2026-09-28T08:15:00Z" }),
    });
    const { client } = renderWithClient(
      <LiveOcrStatus
        slug="s"
        assetId="a1"
        initial={state({ status: "running", pages_total: 2, pages_done: 1 })}
        canRequest={false}
      />,
    );
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await act(() => client.refetchQueries({ queryKey: qk.ocr("s") }));
    await waitFor(() => expect(screen.getByText(/OCR finished/)).toBeInTheDocument());
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.assetDoc("s") });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
