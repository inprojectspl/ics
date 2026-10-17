/** Pure helpers of the PDF reader: canvas limit and error classification. */
import type { MessageKey } from "../../lib/i18n";

/** Upper bound of a single canvas backing store. iOS Safari refuses larger
 * canvases (16 Mpx) and draws nothing, so pdf.js draws high zooms in tiles. */
export const MAX_CANVAS_PIXELS = 16_777_216;

function errorName(e: unknown): string | undefined {
  if (typeof e !== "object" || e === null) return undefined;
  const name = (e as { name?: unknown }).name;
  return typeof name === "string" ? name : undefined;
}

/** Message for a failed document load. pdf.js errors cross the worker
 * boundary as plain objects, so they are told apart by `name`. */
export function loadErrorKey(e: unknown): MessageKey {
  switch (errorName(e)) {
    case "PasswordException":
      return "pdfView.errorPassword";
    case "InvalidPDFException":
      return "pdfView.errorInvalid";
    default:
      return "pdfView.errorLoad";
  }
}
