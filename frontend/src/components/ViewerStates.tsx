import { ReactNode } from "react";
import { clsx } from "clsx";

import { t } from "../lib/i18n";
import { buttonClass } from "./ui/Button";

/** Dead end: the document does not exist or is not shared with this
 * visitor, and the resolver found no way in for them. */
export function NoAccessBlock() {
  return (
    <div className="min-h-[calc(100dvh-3.5rem)] flex items-center justify-center px-(--gutter)">
      <div className="text-center max-w-md">
        <p className="mb-1 text-center text-meta font-medium text-text-secondary">
          {t("viewerStates.unavailable")}
        </p>
        <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("viewerStates.noAccess")}</h1>
        <p className="mb-6 text-center text-ui text-text-secondary">
          {t("viewerStates.noAccessBody")}
        </p>
        <a href="/#login" className={buttonClass()}>
          {t("viewerStates.signIn")}
        </a>
      </div>
    </div>
  );
}

/** A scanned document (HTML bundle, PDF) held for administrator review,
 * as a share visitor sees it. */
export function WithheldNotice({ className }: { className?: string }) {
  return (
    <div className={clsx("rounded-control border border-danger/40 bg-danger/5 px-5 py-4", className)}>
      <p className="text-meta text-danger mb-1 font-medium">
        {t("viewerStates.withheld")}
      </p>
      <p className="text-text-secondary">{t("viewerStates.withheldBody")}</p>
    </div>
  );
}

/** Page-level `WithheldNotice`, standing in for a reader whose payload the
 * backend refused. */
export function WithheldBlock() {
  return (
    <div className="max-w-(--reading-width) mx-auto px-(--gutter) py-16">
      <WithheldNotice />
    </div>
  );
}

/** Look of an informational note, for boxes that are not a plain paragraph. */
export const INFO_NOTE_CLASS =
  "mb-6 rounded-control border border-info/40 bg-info/5 px-4 py-3 text-ui text-text-secondary";

/** Informational note above a reader, e.g. about a scan or a conversion. */
export function InfoNote({ children }: { children: ReactNode }) {
  return <p className={INFO_NOTE_CLASS}>{children}</p>;
}

export function ErrorBlock({ message }: { message: string }) {
  return (
    <div className="min-h-[calc(100dvh-3.5rem)] flex items-center justify-center px-(--gutter)">
      <div className="text-center">
        <p className="mb-1 text-center text-meta font-medium text-text-secondary">{t("viewerStates.error")}</p>
        <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("viewerStates.loadFailed")}</h1>
        <p className="text-text-secondary">{message}</p>
      </div>
    </div>
  );
}

export function Loading() {
  return (
    <div className="max-w-(--reading-width) mx-auto px-(--gutter) py-16">
      <div className="h-10 w-1/2 skeleton rounded mb-3" />
      <div className="h-5 w-1/3 skeleton rounded mb-12" />
      <div className="space-y-3">
        <div className="h-4 skeleton rounded" />
        <div className="h-4 skeleton rounded w-[95%]" />
        <div className="h-4 skeleton rounded w-[90%]" />
      </div>
    </div>
  );
}
