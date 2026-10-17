import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";

import { api } from "../api";
import { Button } from "../components/ui/Button";
import { MarkdownView } from "../components/MarkdownView";
import { PageHeader } from "../components/ui/PageHeader";
import { LiveOcrStatus } from "../components/PdfView";
import { SegmentedToggle } from "../components/SegmentedToggle";
import { INPUT_CLASS } from "../components/Field";
import { Page } from "../components/shell/Page";
import { PageContext } from "../components/shell/PageContext";
import {
  agentViewHref,
  buildMcpCall,
  effectiveFormat,
  isHtmlPath,
  isMultiFile,
  readableFiles,
  type AgentFormat,
  type AgentViewMode,
} from "../lib/agentView";
import { errorCode, formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { hasOcrState } from "../lib/ocr";
import { navigate } from "../lib/navigate";
import { qk } from "../lib/queries";
import { useTheme } from "../lib/theme";
import { useClipboard } from "../lib/useClipboard";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { usePersistedChoice } from "../lib/usePersistedChoice";
import { AgentViewStats } from "../components/AgentViewStats";

interface Props {
  slug: string;
  /** `?p=`: file of a collection or bundle; the entry file when absent. */
  path?: string;
  /** `?fmt=`: how an agent reads an HTML file. */
  format?: AgentFormat;
  /** `?ver=`: archived version. */
  version?: number;
}

const MODES = ["rendered", "source"] as const;

/**
 * Agent view (`/v/<slug>/agent`): the text an MCP agent gets from
 * `ics_asset_read` for one file of the asset, rendered by ICS or as the raw
 * text to copy. For the owner and editors; the backend enforces it.
 */
export function AgentView({ slug, path, format, version }: Props) {
  const theme = useTheme();
  const [mode, onMode] = usePersistedChoice<AgentViewMode>("ics.agentViewMode", MODES, "rendered");
  const { copy, copiedKey } = useClipboard();

  // The three requests start together: the file inventory gives the kind
  // and the entry path, so only a read without `?p=` waits for it.
  const summaryQuery = useQuery({
    queryKey: qk.assetSummary(slug),
    queryFn: () => api.getAssetSummary(slug),
  });
  const filesQuery = useQuery({
    queryKey: qk.agentFiles(slug, version),
    queryFn: () => api.listAgentFiles(slug, version),
  });
  const inventory = filesQuery.data;
  const multi = inventory ? isMultiFile(inventory.kind) : false;
  // Whether the entry is HTML decides the `format` an agent would pass.
  const target = path ?? (multi ? (inventory?.entry_path ?? null) : null);
  const readFormat = effectiveFormat(target, format);
  const read = { path: target, format: readFormat, version };

  const viewQuery = useQuery({
    queryKey: qk.agentView(slug, read),
    queryFn: () => api.getAgentView(slug, read),
    enabled: path !== undefined || filesQuery.isSuccess,
    retry: false,
  });
  const view = viewQuery.data;

  const asset = summaryQuery.data;
  const title = asset?.title ?? slug;
  useDocumentTitle(asset ? `${t("agentView.crumb")} · ${title}` : null);

  const go = useCallback(
    (next: { path?: string | null; format?: AgentFormat }) =>
      navigate(agentViewHref(slug, { ...next, version })),
    [slug, version],
  );

  const error = summaryQuery.error ?? filesQuery.error ?? viewQuery.error;
  const html = mode === "rendered" ? (view?.html ?? null) : null;
  const files = readableFiles((inventory?.files ?? []).map((f) => f.path));

  return (
    <>
      <PageContext
        crumbs={[
          { label: t("nav.documents"), href: "/" },
          { label: title, href: `/v/${slug}${version ? `?ver=${version}` : ""}` },
          { label: t("agentView.crumb") },
        ]}
      />
      <Page width="reading">
        <PageHeader title={t("agentView.title")} description={t("agentView.description")} />

        <div className="mb-4 flex flex-wrap items-center gap-3">
          {multi && files.length > 0 && (
            <label className="flex min-w-0 w-full items-center gap-2 sm:w-auto sm:max-w-md">
              <span className="shrink-0 text-meta text-text-secondary">
                {t("agentView.file")}
              </span>
              <select
                value={target ?? ""}
                onChange={(e) => go({ path: e.target.value, format })}
                className={`${INPUT_CLASS} min-w-0 flex-1 px-2 font-code`}
              >
                {files.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
          )}
          {isHtmlPath(target) && (
            <SegmentedToggle
              value={readFormat ?? "markdown"}
              onChange={(f) => go({ path: target, format: f })}
              ariaLabel={t("agentView.formatLabel")}
              options={[
                {
                  value: "markdown",
                  label: t("agentView.formatMarkdown"),
                  tooltip: t("agentView.formatMarkdownHint"),
                },
                { value: "raw", label: t("agentView.formatRaw") },
              ]}
            />
          )}
          {view && view.html !== null && (
            <SegmentedToggle
              value={mode}
              onChange={onMode}
              ariaLabel={t("agentView.modeLabel")}
              options={[
                { value: "rendered", label: t("agentView.modeRendered") },
                { value: "source", label: t("agentView.modeSource") },
              ]}
            />
          )}
          {view && (
            <Button
              variant="secondary"
              className="ml-auto"
              icon={copiedKey === "content" ? <Check size={15} aria-hidden /> : <Copy size={15} aria-hidden />}
              onClick={() => void copy(view.content, "content")}
            >
              {copiedKey === "content" ? t("agentView.copied") : t("agentView.copy")}
            </Button>
          )}
        </div>

        {view && (
          <AgentViewStats
            view={view}
            call={buildMcpCall(slug, {
              path: isMultiFile(view.kind) ? view.path : null,
              format: readFormat,
              version,
            })}
            copy={copy}
            copiedKey={copiedKey}
          />
        )}

        {view && hasOcrState(view.ocr) && asset && (
          <LiveOcrStatus
            slug={slug}
            assetId={asset.id}
            version={version}
            initial={view.ocr}
            pageCount={view.page_count}
            canRequest={version === undefined || version === view.current_version}
          />
        )}

        {error ? (
          <p className="text-ui text-danger">{errorText(error)}</p>
        ) : !view ? (
          <p role="status" className="py-12 text-center text-meta text-text-secondary">{t("agentView.loading")}</p>
        ) : view.content === "" ? (
          <p className="py-12 text-center text-meta text-text-secondary">{t("agentView.empty")}</p>
        ) : html !== null ? (
          // The reader brings its own gutter.
          <div className="-mx-(--gutter) rounded-card border border-border bg-surface max-sm:rounded-none max-sm:border-x-0">
            <MarkdownView html={html} theme={theme} />
          </div>
        ) : (
          <pre
            aria-label={t("agentView.modeSource")}
            className="overflow-x-auto whitespace-pre-wrap break-words rounded-card border border-border bg-code-bg px-4 py-3 font-code text-ui leading-relaxed text-code-ink sm:px-5 sm:py-4"
          >
            {view.content}
          </pre>
        )}
      </Page>
    </>
  );
}

function errorText(e: unknown): string {
  // A binary file is not an error of the view: the agent gets it as base64.
  if (errorCode(e) === "binary_file") return t("agentView.binary");
  return formatApiError(e);
}
