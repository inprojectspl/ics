import { Suspense, lazy, type ReactNode } from "react";
import { Download } from "lucide-react";
import type { PdfInfo, SecurityReport, SecurityStatus } from "../../api";
import { t } from "../../lib/i18n";
import { mt } from "../../styles/markdown-theme";
import { buttonClass } from "../ui/Button";
import { SecurityFindings } from "../SecurityFindings";
import { InfoNote, WithheldNotice } from "../ViewerStates";

// The reader pulls in pdfjs-dist; only a PDF page pays for it.
const PdfReader = lazy(() => import("./PdfReader").then((m) => ({ default: m.PdfReader })));

interface Props {
  /** Endpoint with the PDF bytes, see `pdfUrl` / `sharePdfUrl`. */
  url: string;
  title: string | null;
  meta?: string | null;
  info?: PdfInfo | null;
  downloadHref?: string;
  securityStatus?: SecurityStatus | null;
  securityReport?: SecurityReport | null;
  securityBypass?: boolean;
  /** Share visitor on a document held for review: show the notice instead
   * of the pages (the backend refuses the bytes anyway). */
  accessGated?: boolean;
  /** OCR state of a scan (`OcrStatusView` / `LiveOcrStatus`); without it a
   * scan gets the plain "no text layer" note. */
  ocr?: ReactNode;
}

/** Reader page of a pdf_doc: header, security findings, the OCR state (or a
 * note) for scans and the lazily loaded page renderer. */
export function PdfDocument({
  url,
  title,
  meta,
  info,
  downloadHref,
  securityStatus,
  securityReport,
  securityBypass,
  accessGated = false,
  ocr,
}: Props) {
  const scanned = info != null && info.page_count > 0 && info.text_page_count === 0;
  return (
    <article className="max-w-4xl mx-auto px-(--gutter) py-10">
      <div className="flex items-start justify-between gap-4">
        {meta ? <div className={mt.meta}>{meta}</div> : <span aria-hidden />}
        {downloadHref && !accessGated && (
          <a href={downloadHref} download className={buttonClass("secondary", "sm")}>
            <Download size={16} aria-hidden />
            {t("pdfView.download")}
          </a>
        )}
      </div>
      {title && <h1 className={mt.title}>{title}</h1>}

      <SecurityFindings status={securityStatus} report={securityReport} bypassed={securityBypass} />

      {ocr ?? (scanned && <InfoNote>{t("pdfView.scannedNote")}</InfoNote>)}

      {accessGated ? (
        <WithheldNotice />
      ) : (
        <Suspense
          fallback={
            <p className="py-12 text-center text-text-tertiary">{t("pdfView.loading")}</p>
          }
        >
          <PdfReader url={url} title={title} downloadHref={downloadHref} />
        </Suspense>
      )}
    </article>
  );
}
