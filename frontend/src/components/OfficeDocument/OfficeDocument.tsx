import type {
  OfficeDocumentInfo,
  SecurityReport,
  SecurityStatus,
} from "../../api";
import { t, tn } from "../../lib/i18n";
import type { Theme } from "../../lib/theme";
import { MarkdownView } from "../MarkdownView";
import { SecurityFindings } from "../SecurityFindings";
import { InfoNote, WithheldNotice } from "../ViewerStates";

interface Props {
  /** Sanitized HTML the backend rendered from the converted document. */
  html: string;
  theme: Theme;
  title: string | null;
  meta?: string | null;
  info?: OfficeDocumentInfo | null;
  downloadHref?: string;
  securityStatus?: SecurityStatus | null;
  securityReport?: SecurityReport | null;
  securityBypass?: boolean;
  /** Share visitor on a document held for review: show the notice instead
   * of the text and the download. */
  accessGated?: boolean;
}

/** Reader page of an office_doc: the converted text rendered like a
 * Markdown document (read-only), with notes about the conversion. */
export function OfficeDocument({
  html,
  theme,
  title,
  meta,
  info,
  downloadHref,
  securityStatus,
  securityReport,
  securityBypass,
  accessGated = false,
}: Props) {
  return (
    <MarkdownView
      html={accessGated ? "" : html}
      theme={theme}
      title={title}
      meta={meta}
      downloadHref={accessGated ? undefined : downloadHref}
      downloadLabel={t("officeDocument.downloadOriginal")}
    >
      <SecurityFindings status={securityStatus} report={securityReport} bypassed={securityBypass} />
      {accessGated ? (
        <WithheldNotice className="mb-6" />
      ) : (
        <>
          {info && (
            <InfoNote>
              {t("officeDocument.convertedNote", { format: `.${info.source_format}` })}
            </InfoNote>
          )}
          {info && info.images > 0 && <InfoNote>{tn("officeDocument.imagesNote", info.images)}</InfoNote>}
        </>
      )}
    </MarkdownView>
  );
}
