// OCR of scanned PDFs (ADR-0021), as `services/ocr/state.py` serializes it.

/** OCR of a PDF version (ADR-0021): `not_requested` until a run is queued. */
type OcrStatus = "not_requested" | "queued" | "running" | "done" | "failed";

/** An OCR engine a reader may pick; a cloud one takes the reader's API key. */
export type OcrProviderInfo = { name: string; needs_api_key: boolean };

/** Body of `POST /{id}/ocr`: engine and, for a cloud one, the API key. */
export type OcrRequest = { provider?: string; api_key?: string };

export type OcrState = {
  status: OcrStatus;
  /** Pages without a text layer, the ones OCR reads; 0 means nothing to do. */
  pages_without_text: number;
  /** Scans whose text is an invisible layer saved in the file (e.g. by the
   * scanner): quality unknown, OCR recommended; a request replaces it. */
  pages_with_hidden_text: number;
  /** False when the operator turned OCR off. */
  available: boolean;
  provider: string | null;
  requested_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  pages_total: number | null;
  pages_done: number | null;
  pages_recognized: number | null;
  /** Engines a request may name; the first is the default. */
  providers: OcrProviderInfo[];
  /** Stable reason of a failed run (`ocr_timeout`, `ocr_engine_failed`, ...). */
  error_code: string | null;
};

/** `GET /by-slug/{slug}/ocr` and `POST /{id}/ocr`. */
export type OcrResponse = { slug: string; version: number; ocr: OcrState };
