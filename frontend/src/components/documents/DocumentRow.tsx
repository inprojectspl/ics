import { memo, useMemo, useState } from "react";
import { clsx } from "clsx";
import { GitBranch, Star } from "lucide-react";
import type { AssetSummary, ProjectSummary } from "../../api";
import { buildAssetMenuActions } from "../../lib/assetMenuActions";
import { type AssetSortKey, lastChange } from "../../lib/assetSort";
import { formatBytes, formatDateTime, formatRelative, formatShortDate, versionCountLabel } from "../../lib/format";
import { t } from "../../lib/i18n";
import { PROJECT_ROLE_LABEL } from "../../lib/roles";
import { togglePin, type AssetRowActions } from "../../lib/useAssetActions";
import { DocTypeBadge, FreshnessBadge } from "../AssetMetaBadges";
import { AppLink } from "../ui/AppLink";
import { iconButtonClass } from "../ui/IconButton";
import { Menu } from "../ui/Menu";
import { Badge } from "../ui/Badge";
import { dataRow } from "../ui/DataList";
import { KIND_LABEL, KindTile } from "./kindIcon";
import { SecurityStatusBadge, ShareStatus } from "./ShareStatus";

interface Props {
  asset: AssetSummary;
  projectsById: ReadonlyMap<string, ProjectSummary>;
  onCommitRename: (assetId: string, next: string) => void;
  onPinChanged: (pinned: boolean) => void;
  actions: AssetRowActions;
  /** The row stresses the value the list is sorted by. */
  sortKey?: AssetSortKey;
  /** Leave out the project (the project page lists only its own). */
  hideProject?: boolean;
}

// Only devices that really hover hide the favourite star at rest; touch
// screens always show it, and the menu carries the same action.
const HOVER_REVEAL =
  "[@media(hover:hover)]:opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100";

function DocumentRowImpl({
  asset: a,
  projectsById,
  onCommitRename,
  onPinChanged,
  actions,
  sortKey = "updated",
  hideProject = false,
}: Props) {
  const [renaming, setRenaming] = useState<string | null>(null);
  const title = a.title ?? a.slug;
  const pinned = Boolean(a.pinned_at);
  const project = !hideProject && a.project_id ? projectsById.get(a.project_id) : undefined;
  const owner = a.owner ? a.owner.display_name || a.owner.email : null;

  // One action list for the dropdown, the phone sheet and the reader toolbar.
  const menu = useMemo(
    () => [
      {
        key: "pin",
        label: t(pinned ? "pinButton.remove" : "pinButton.add"),
        icon: Star,
        onClick: () => void togglePin(a.id, pinned, onPinChanged),
      },
      ...buildAssetMenuActions(a, actions, { onRename: () => setRenaming(title) }),
    ],
    [a, actions, pinned, title, onPinChanged],
  );

  return (
    <li className={dataRow({ align: "start" })}>
      <KindTile kind={a.kind} className="mt-0.5" />

      <div className="min-w-0 flex-1">
        {renaming !== null ? (
          <form
            className="relative z-10"
            onSubmit={(e) => {
              e.preventDefault();
              const next = renaming.trim();
              if (next && next !== title) onCommitRename(a.id, next);
              setRenaming(null);
            }}
          >
            <input
              autoFocus
              aria-label={t("assetToolbar.nameLabel")}
              value={renaming}
              onChange={(e) => setRenaming(e.target.value)}
              onBlur={() => setRenaming(null)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setRenaming(null);
              }}
              className="w-full rounded-control border border-accent bg-surface px-2 py-1 text-item font-semibold text-text-primary outline-none ring-2 ring-accent/25"
            />
          </form>
        ) : (
          <AppLink
            href={`/v/${a.slug}`}
            title={title}
            className={clsx(
              "line-clamp-2 text-item font-semibold text-text-primary [overflow-wrap:anywhere]",
              // The title is the row's link; its hit area covers the whole row.
              "after:absolute after:inset-0 after:content-['']",
              "focus-visible:outline-none focus-visible:after:rounded-control focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-accent",
            )}
          >
            {title}
          </AppLink>
        )}

        {a.summary && (
          <p className="mt-0.5 line-clamp-1 text-ui text-text-secondary" title={a.summary}>
            {a.summary}
          </p>
        )}

        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-meta text-text-secondary">
          <span className="sr-only">{t(KIND_LABEL[a.kind])}</span>
          <span className={clsx("tabular-nums", sortKey === "versions" && EMPHASIS)} title={versionCountLabel(a.version)}>
            v{a.version}
          </span>
          <Sep />
          <RowDate asset={a} sortKey={sortKey} />
          <span className="hidden items-center gap-x-2 sm:inline-flex">
            <Sep />
            <span className="tabular-nums">{formatBytes(a.size_bytes)}</span>
          </span>
          {owner && (
            <>
              <Sep />
              <span className="min-w-0 max-w-[14rem] truncate" title={t("assetRow.ownerTitle", { name: owner, email: a.owner?.email ?? "" })}>
                {t("assetRow.byOwner", { name: owner })}
                {a.my_role && a.my_role !== "owner" ? ` · ${t(PROJECT_ROLE_LABEL[a.my_role])}` : ""}
              </span>
            </>
          )}
          {project && (
            <>
              <Sep />
              <AppLink
                href={`/projects/${project.slug}`}
                className="relative z-10 min-w-0 max-w-[14rem] truncate font-medium text-text-secondary underline-offset-2 hover:text-accent hover:underline"
                title={t("assetRow.projectTitle", { name: project.name })}
              >
                {project.name}
              </AppLink>
            </>
          )}
          {a.has_binding && (
            <>
              <Sep />
              <span className="inline-flex items-center gap-1" title={t("assetRow.gitlabSynced")}>
                <GitBranch size={12} aria-hidden />
                GitLab
              </span>
            </>
          )}
          {a.doc_type && <DocTypeBadge docType={a.doc_type} />}
          <FreshnessBadge freshness={a.freshness} />
          {a.shared_in && <Badge tone="accent">{t("projectShares.sharedIn")}</Badge>}
          <span className="contents sm:hidden">
            <ShareStatus modes={a.active_share_modes} />
          </span>
          <SecurityStatusBadge status={a.security_status} bypassed={a.security_bypass} />
        </div>
      </div>

      <div className="relative z-10 flex shrink-0 items-center gap-1 self-center sm:gap-2">
        <span className="hidden sm:inline-flex">
          <ShareStatus modes={a.active_share_modes} />
        </span>
        <button
          type="button"
          onClick={() => void togglePin(a.id, pinned, onPinChanged)}
          aria-pressed={pinned}
          aria-label={t(pinned ? "pinButton.remove" : "pinButton.add")}
          title={t(pinned ? "pinButton.remove" : "pinButton.add")}
          className={clsx(
            iconButtonClass("ghost", "sm"),
            "max-sm:hidden",
            pinned ? "text-accent" : HOVER_REVEAL,
          )}
        >
          <Star size={16} aria-hidden className={pinned ? "fill-current" : undefined} />
        </button>
        <Menu label={t("documentRow.actions", { title })} actions={menu} />
      </div>
    </li>
  );
}

export const DocumentRow = memo(DocumentRowImpl);

const EMPHASIS = "font-medium text-text-primary";

function Sep() {
  return (
    <span aria-hidden className="text-text-tertiary">
      ·
    </span>
  );
}

function RowDate({ asset: a, sortKey }: { asset: AssetSummary; sortKey: AssetSortKey }) {
  const created = sortKey === "created";
  const iso = created ? a.created_at : lastChange(a);
  return (
    <time
      dateTime={iso}
      title={formatDateTime(iso) ?? undefined}
      className={clsx("whitespace-nowrap", (created || sortKey === "updated") && "text-text-primary")}
    >
      {created
        ? t("assetRow.createdOn", { date: formatShortDate(iso) })
        : t("assetRow.changed", { when: formatRelative(iso) })}
    </time>
  );
}
