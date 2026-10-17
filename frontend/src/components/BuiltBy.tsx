import { clsx } from "clsx";
import { t } from "../lib/i18n";
import { InProjectsLogo } from "./InProjectsLogo";

export const INPROJECTS_URL = "https://inprojects.ai";

/**
 * Credit for the team behind ICS, linking to inProjects.ai. `page` sits under
 * the pre-auth card, `sidebar` in the sidebar footer; the collapsed rail uses
 * `RailCredit`.
 */
export function BuiltBy({ variant }: { variant: "page" | "sidebar" }) {
  return (
    <a
      href={INPROJECTS_URL}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={t("builtBy.linkLabel")}
      className={clsx(
        "inline-flex items-center gap-2 rounded-control text-meta text-text-tertiary transition-colors duration-150 hover:text-text-secondary",
        variant === "page" ? "px-2 py-1" : "px-2 py-1.5",
      )}
    >
      <span>{t("builtBy.label")}</span>
      <InProjectsLogo height={variant === "page" ? 18 : 15} />
    </a>
  );
}
