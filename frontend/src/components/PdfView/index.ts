// Only the light shell is exported: it lazy-loads `PdfReader` (and pdfjs-dist
// with it), so importing the package never pulls the renderer eagerly.
export { PdfDocument } from "./PdfDocument";
export { LiveOcrStatus, OcrStatusView } from "./OcrStatus";
