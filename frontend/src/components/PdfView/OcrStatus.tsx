import { useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, RotateCw, ScanText } from "lucide-react";
import { api, type OcrProviderInfo, type OcrRequest, type OcrState } from "../../api";
import { formatApiError } from "../../lib/apiError";
import { formatDateTime } from "../../lib/format";
import { formatNumber, t, tn } from "../../lib/i18n";
import { failureReason, hasOcrState, providerLabel } from "../../lib/ocr";
import { qk } from "../../lib/queries";
import { Button, buttonClass } from "../ui/Button";
import { Field, INPUT_CLASS } from "../Field";
import { INFO_NOTE_CLASS } from "../ViewerStates";

const ACTIVE = new Set(["queued", "running"]);
// Often enough to feel live on a short scan, rare enough for a long queue.
const POLL_MS = 3000;

interface ViewProps {
  state: OcrState;
  /** Queue a run (first one or retry); absent for readers who cannot. */
  onRequest?: (request: OcrRequest) => void;
  busy?: boolean;
  error?: string | null;
  /** Where the recognized text can be read; absent when the reader has no view. */
  textHref?: string | null;
  /** Pages of the whole document: a run reads only some of them. */
  pageCount?: number;
}

/** OCR state of a scanned PDF: what happened to the pages without a text
 * layer, and the action that fits (run, retry, read the text). Renders
 * nothing for a PDF whose pages all have text. */
export function OcrStatusView({
  state,
  onRequest,
  busy = false,
  error,
  textHref,
  pageCount,
}: ViewProps) {
  if (!hasOcrState(state)) return null;
  const active = ACTIVE.has(state.status);
  const firstRun = state.status === "not_requested";
  // Text to read: recognized by a finished run, or a layer the file carries.
  const hasText = state.status === "done" || state.pages_with_hidden_text > 0;
  const canRequest = onRequest !== undefined && state.available && !active;
  const finished = formatDateTime(state.finished_at);

  let message: string;
  switch (state.status) {
    case "not_requested":
      if (!state.available) message = t("ocrStatus.disabled");
      else if (state.pages_without_text > 0)
        message = tn("ocrStatus.notRequested", state.pages_without_text);
      else message = tn("ocrStatus.hiddenText", state.pages_with_hidden_text);
      break;
    case "queued":
      message = t("ocrStatus.queued");
      break;
    case "running":
      message = state.pages_total
        ? t("ocrStatus.running", { done: state.pages_done ?? 0, total: state.pages_total })
        : t("ocrStatus.starting");
      break;
    case "done":
      message = t("ocrStatus.done", {
        date: finished ?? "",
        provider: providerLabel(state.provider),
        found: state.pages_recognized ?? 0,
        total: state.pages_total ?? 0,
      });
      break;
    case "failed":
      message = t("ocrStatus.failed", {
        date: finished ?? "",
        reason: failureReason(state.error_code),
      });
      break;
  }
  // Without this a run over a few scans reads as if it covered the whole file.
  const unread = pageCount !== undefined && state.pages_total ? pageCount - state.pages_total : 0;
  if ((state.status === "running" || state.status === "done") && unread > 0) {
    message += ` ${tn("ocrStatus.otherPages", unread, { pages: formatNumber(pageCount ?? 0) })}`;
  }
  const progress =
    state.status === "running" && state.pages_total
      ? Math.round(((state.pages_done ?? 0) / state.pages_total) * 100)
      : null;

  return (
    <section
      aria-label={t("ocrStatus.label")}
      aria-live="polite"
      className={INFO_NOTE_CLASS}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <ScanText size={18} aria-hidden className="shrink-0 text-info" />
        <p className="flex-1 min-w-48">{message}</p>
        {textHref && hasText && (
          <a href={textHref} className={buttonClass("secondary", "sm")}>
            <FileText size={16} aria-hidden />
            {t("ocrStatus.showText")}
          </a>
        )}
      </div>
      {canRequest && (
        <RequestForm
          providers={state.providers}
          firstRun={firstRun}
          busy={busy}
          onRequest={onRequest}
        />
      )}
      {progress !== null && (
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
          className="mt-3 h-1.5 overflow-hidden rounded-full bg-info/15"
        >
          <div className="h-full bg-info transition-[width]" style={{ width: `${progress}%` }} />
        </div>
      )}
      {error && (
        <p role="alert" className="mt-2 text-danger">
          {error}
        </p>
      )}
    </section>
  );
}

/** The run button, with the engine choice when there is more than one; a
 * cloud engine asks for the reader's API key, which goes to this run only. */
function RequestForm({
  providers,
  firstRun,
  busy,
  onRequest,
}: {
  providers: OcrProviderInfo[];
  firstRun: boolean;
  busy: boolean;
  onRequest: (request: OcrRequest) => void;
}) {
  const [provider, setProvider] = useState(providers[0]?.name ?? "");
  const [apiKey, setApiKey] = useState("");
  const needsKey = providers.find((p) => p.name === provider)?.needs_api_key ?? false;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (providers.length <= 1) onRequest({});
    else onRequest(needsKey ? { provider, api_key: apiKey.trim() } : { provider });
  };
  return (
    <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-3">
      {providers.length > 1 && (
        <Field label={t("ocrStatus.engine")}>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className={INPUT_CLASS}
          >
            {providers.map((p) => (
              <option key={p.name} value={p.name}>
                {providerLabel(p.name)}
              </option>
            ))}
          </select>
        </Field>
      )}
      {needsKey && (
        <div className="min-w-56 flex-1">
          <Field label={t("ocrStatus.apiKey")}>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className={`${INPUT_CLASS} font-code`}
            />
          </Field>
        </div>
      )}
      <Button
        type="submit"
        variant={firstRun ? "primary" : "secondary"}
        size="sm"
        disabled={busy || (needsKey && apiKey.trim() === "")}
      >
        {firstRun ? <ScanText size={16} aria-hidden /> : <RotateCw size={16} aria-hidden />}
        {firstRun ? t("ocrStatus.run") : t("ocrStatus.retry")}
      </Button>
      {needsKey && <p className="w-full text-meta text-text-tertiary">{t("ocrStatus.cloudNote")}</p>}
    </form>
  );
}

interface LiveProps {
  slug: string;
  assetId: string;
  /** Archived version being previewed; OCR requests go to the current one. */
  version?: number;
  initial: OcrState;
  /** Editor or higher on the current version. */
  canRequest: boolean;
  textHref?: string | null;
  pageCount?: number;
}

/** `OcrStatusView` kept current: polls while a run is queued or running,
 * and refreshes the document once a run ends (its text and counts change). */
export function LiveOcrStatus({
  slug,
  assetId,
  version,
  initial,
  canRequest,
  textHref,
  pageCount,
}: LiveProps) {
  const queryClient = useQueryClient();
  const lastStatus = useRef(initial.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = qk.ocr(slug, version);

  const query = useQuery({
    queryKey: key,
    queryFn: async () => {
      const r = await api.getOcr(slug, version);
      const was = lastStatus.current;
      lastStatus.current = r.ocr.status;
      if (ACTIVE.has(was) && !ACTIVE.has(r.ocr.status)) {
        void queryClient.invalidateQueries({ queryKey: qk.assetDoc(slug) });
        void queryClient.invalidateQueries({ queryKey: qk.agentViews(slug) });
      }
      return r.ocr;
    },
    initialData: initial,
    // Only a run in progress changes on its own; the document query refreshes the rest.
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? POLL_MS : false),
    refetchOnWindowFocus: (q) => q.state.data !== undefined && ACTIVE.has(q.state.data.status),
  });

  const onRequest = async (request: OcrRequest) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.requestOcr(assetId, request);
      lastStatus.current = r.ocr.status;
      queryClient.setQueryData(key, r.ocr);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <OcrStatusView
      state={query.data}
      onRequest={canRequest ? onRequest : undefined}
      busy={busy}
      error={error}
      textHref={textHref}
      pageCount={pageCount}
    />
  );
}
