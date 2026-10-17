import { useState } from "react";
import { ArrowRight, X } from "lucide-react";
import type { SupersededBy } from "../api";
import { formatDay } from "../lib/format";
import { t } from "../lib/i18n";
import { isPlainClick, navigate } from "../lib/navigate";

interface Props {
  /** The successor as the backend sent it: only one this reader can open. */
  successor: SupersededBy;
}

/**
 * "A newer document replaces this one" banner, drawn next to the archived
 * version banner (`StaleVersionNotice`) and styled like it, in normal flow
 * and without `z-index` for the same reasons. An HTML bundle on the isolated
 * viewer gets the equivalent from the backend (`app/services/version_banner.py`).
 */
export function SupersededBanner({ successor }: Props) {
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;

  const title = successor.title || t("viewer.supersededUntitled");
  const since = successor.since;
  const date = since && !Number.isNaN(Date.parse(since)) ? formatDay(since) : null;

  return (
    <div role="alert" className="relative border-b border-warning/40 bg-warning/10 px-(--gutter) py-2.5">
      <div className="flex items-start gap-3 pr-8 text-ui">
        <ArrowRight size={16} className="mt-0.5 shrink-0 text-warning" aria-hidden />
        <p className="text-text-primary">
          {date
            ? t("viewer.supersededBanner", { title, date })
            : t("viewer.supersededBannerUndated", { title })}{" "}
          <a
            href={successor.href}
            onClick={(e) => {
              // Let the browser handle new-tab clicks; a plain click stays in the SPA.
              if (!isPlainClick(e)) return;
              e.preventDefault();
              navigate(successor.href);
            }}
            className="text-accent underline hover:no-underline"
          >
            {t("viewer.supersededOpen")}
          </a>
        </p>
      </div>
      <button
        type="button"
        onClick={() => setHidden(true)}
        aria-label={t("viewer.supersededHide")}
        className="absolute top-1.5 right-2 inline-flex h-7 w-7 items-center justify-center rounded-control text-text-tertiary hover:bg-surface-subtle hover:text-text-primary"
      >
        <X size={15} aria-hidden />
      </button>
    </div>
  );
}
