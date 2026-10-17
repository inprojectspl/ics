import { useState, type FormEvent, type KeyboardEvent } from "react";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Download,
  Maximize2,
  Minimize2,
  MoveHorizontal,
  Search,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { clsx } from "clsx";
import { formatNumber, t } from "../../lib/i18n";
import { inputClass } from "../Field";

export interface FindState {
  query: string;
  /** Match being shown (1-based) and all matches; 0 while none. */
  current: number;
  total: number;
  /** The search finished without a match. */
  notFound: boolean;
}

interface Props {
  page: number;
  pages: number;
  /** Current zoom in percent. */
  zoom: number;
  onPage: (page: number) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitWidth: () => void;
  find: FindState;
  searchOpen: boolean;
  onSearchOpen: (open: boolean) => void;
  onFind: (query: string, again?: "next" | "previous") => void;
  expanded: boolean;
  onExpand: (expanded: boolean) => void;
  title?: string | null;
  downloadHref?: string;
  /** No document yet (loading, error): navigation and zoom are disabled. */
  disabled: boolean;
}

const ICON = "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-control text-text-secondary hover:bg-surface-subtle hover:text-text-primary disabled:opacity-40 disabled:pointer-events-none";

function IconButton({
  label,
  onClick,
  disabled,
  active,
  className,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={clsx(ICON, active && "bg-surface-subtle text-text-primary", className)}
      aria-label={label}
      title={label}
      aria-pressed={active}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

/** Controls of the PDF reader: pages, zoom, search, download, full screen. */
export function PdfToolbar(props: Props) {
  const { page, pages, zoom, disabled, find, searchOpen, expanded } = props;
  // Embedded on a phone the bar keeps pages, search and full screen: zoom is
  // a pinch away (and in full screen), the download is in the page header.
  const wide = expanded ? "" : "max-sm:hidden";
  // The field shows what is typed until it is committed, then the page again.
  const [draft, setDraft] = useState<{ page: number; value: string } | null>(null);
  const shown = draft && draft.page === page ? draft.value : String(page);

  const commitPage = (e: FormEvent) => {
    e.preventDefault();
    const n = Number.parseInt(shown, 10);
    if (Number.isFinite(n)) props.onPage(Math.min(Math.max(n, 1), pages));
    setDraft(null);
  };
  const onSearchKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      props.onFind(find.query, e.shiftKey ? "previous" : "next");
    } else if (e.key === "Escape") {
      e.stopPropagation();
      props.onSearchOpen(false);
    }
  };

  return (
    <div className="shrink-0 border-b border-border bg-surface">
      <div
        role="toolbar"
        aria-label={t("pdfView.toolbar")}
        className="flex items-center gap-1 px-2 py-1.5"
      >
        {expanded && props.title && (
          <p className="mr-2 hidden min-w-0 max-w-[30%] truncate text-ui text-text-primary md:block">
            {props.title}
          </p>
        )}
        <IconButton
          label={t("pdfView.prevPage")}
          onClick={() => props.onPage(page - 1)}
          disabled={disabled || page <= 1}
        >
          <ChevronLeft size={18} aria-hidden />
        </IconButton>
        <form onSubmit={commitPage} className="flex items-center gap-1 text-ui text-text-secondary">
          <input
            aria-label={t("pdfView.pageInput")}
            inputMode="numeric"
            value={disabled ? "" : shown}
            disabled={disabled}
            onChange={(e) => setDraft({ page, value: e.target.value })}
            onBlur={commitPage}
            className={`${inputClass({ size: "sm", full: false })} w-12 !px-1 text-center tabular-nums`}
          />
          <span className="whitespace-nowrap tabular-nums">
            {t("pdfView.pageOf", { total: formatNumber(pages) })}
          </span>
        </form>
        <IconButton
          label={t("pdfView.nextPage")}
          onClick={() => props.onPage(page + 1)}
          disabled={disabled || page >= pages}
        >
          <ChevronRight size={18} aria-hidden />
        </IconButton>

        <span className={clsx("mx-1 h-5 w-px bg-border", wide)} aria-hidden />
        <IconButton
          label={t("pdfView.zoomOut")}
          onClick={props.onZoomOut}
          disabled={disabled}
          className={wide}
        >
          <ZoomOut size={18} aria-hidden />
        </IconButton>
        <span className="hidden w-12 text-center text-ui tabular-nums text-text-secondary sm:inline">
          {disabled ? "" : `${formatNumber(zoom)}%`}
        </span>
        <IconButton
          label={t("pdfView.zoomIn")}
          onClick={props.onZoomIn}
          disabled={disabled}
          className={wide}
        >
          <ZoomIn size={18} aria-hidden />
        </IconButton>
        <span className="hidden sm:contents">
          <IconButton label={t("pdfView.fitWidth")} onClick={props.onFitWidth} disabled={disabled}>
            <MoveHorizontal size={18} aria-hidden />
          </IconButton>
        </span>

        <span className="ml-auto" />
        <IconButton
          label={t("pdfView.search")}
          onClick={() => props.onSearchOpen(!searchOpen)}
          disabled={disabled}
          active={searchOpen}
        >
          <Search size={18} aria-hidden />
        </IconButton>
        {props.downloadHref && (
          <a
            href={props.downloadHref}
            download
            className={clsx(ICON, wide)}
            aria-label={t("pdfView.download")}
            title={t("pdfView.download")}
          >
            <Download size={18} aria-hidden />
          </a>
        )}
        <IconButton
          label={expanded ? t("pdfView.exitFullscreen") : t("pdfView.fullscreen")}
          onClick={() => props.onExpand(!expanded)}
        >
          {expanded ? <Minimize2 size={18} aria-hidden /> : <Maximize2 size={18} aria-hidden />}
        </IconButton>
      </div>

      {searchOpen && (
        <div className="flex items-center gap-1 border-t border-border px-2 py-1.5">
          <input
            type="search"
            // The search row opens on request, so the field takes the focus.
            autoFocus
            aria-label={t("pdfView.search")}
            placeholder={t("pdfView.searchPlaceholder")}
            value={find.query}
            onChange={(e) => props.onFind(e.target.value)}
            onKeyDown={onSearchKey}
            className={`${inputClass({ size: "sm", full: false })} min-w-0 flex-1 !px-2`}
          />
          <span className="min-w-16 text-center text-meta tabular-nums text-text-tertiary" aria-live="polite">
            {find.query === ""
              ? ""
              : find.notFound
                ? t("pdfView.noMatches")
                : find.total > 0
                  ? t("pdfView.matches", {
                      current: formatNumber(find.current),
                      total: formatNumber(find.total),
                    })
                  : ""}
          </span>
          <IconButton
            label={t("pdfView.searchPrev")}
            onClick={() => props.onFind(find.query, "previous")}
            disabled={find.total === 0}
          >
            <ChevronUp size={18} aria-hidden />
          </IconButton>
          <IconButton
            label={t("pdfView.searchNext")}
            onClick={() => props.onFind(find.query, "next")}
            disabled={find.total === 0}
          >
            <ChevronDown size={18} aria-hidden />
          </IconButton>
          <IconButton label={t("pdfView.searchClose")} onClick={() => props.onSearchOpen(false)}>
            <X size={18} aria-hidden />
          </IconButton>
        </div>
      )}
    </div>
  );
}
