import { ChevronLeft, ChevronRight } from "lucide-react";
import { t } from "../lib/i18n";
import { IconButton } from "./ui/IconButton";

interface Props {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}

/** Pager of every paged list: the visible range and previous/next. */
export function Pagination({ page, pageSize, total, onPage }: Props) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  if (pageCount <= 1) return null;
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);
  return (
    <nav aria-label={t("pagination.label")} className="mt-4 flex items-center justify-between gap-4 text-meta text-text-secondary">
      <span className="tabular-nums">{t("homePagination.range", { start, end, total })}</span>
      <div className="flex items-center gap-1">
        <IconButton
          label={t("pagination.previous")}
          icon={<ChevronLeft size={16} aria-hidden />}
          onClick={() => onPage(Math.max(1, page - 1))}
          disabled={page <= 1}
          size="sm"
        />
        <span aria-live="polite" className="px-1.5 tabular-nums">
          {t("pagination.pageOf", { page, pageCount })}
        </span>
        <IconButton
          label={t("pagination.next")}
          icon={<ChevronRight size={16} aria-hidden />}
          onClick={() => onPage(Math.min(pageCount, page + 1))}
          disabled={page >= pageCount}
          size="sm"
        />
      </div>
    </nav>
  );
}
