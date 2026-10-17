import { memo } from "react";
import { Bot, ExternalLink, Files, Network, Sparkles, Users } from "lucide-react";
import type { ProjectSummary } from "../../api";
import { t, tn } from "../../lib/i18n";
import { navigate } from "../../lib/navigate";
import { AppLink } from "../ui/AppLink";
import { DATA_ROW } from "../ui/DataList";
import { Menu } from "../ui/Menu";
import type { MenuAction } from "../ui/menuAction";
import { ProjectMonogram } from "./ProjectMonogram";
import { ProjectRoleBadge } from "./ProjectRoleBadge";

/** One project in the list: opens on click, its views in the `…` menu. */
function ProjectRowImpl({ project: p }: { project: ProjectSummary }) {
  const base = `/projects/${p.slug}`;
  const member = p.my_role !== null;
  const maintain = p.my_role === "owner" || p.my_role === "editor";
  const actions: MenuAction[] = [
    { key: "open", label: t("common.open"), icon: ExternalLink, onClick: () => navigate(base) },
    ...(member ? [{ key: "map", label: t("projectTabs.map"), icon: Network, onClick: () => navigate(`${base}/map`) }] : []),
    ...(maintain ? [{ key: "hygiene", label: t("projectTabs.hygiene"), icon: Sparkles, onClick: () => navigate(`${base}/hygiene`) }] : []),
    ...(member ? [{ key: "agent", label: t("projectTabs.agent"), icon: Bot, onClick: () => navigate(`${base}/agent`) }] : []),
  ];
  return (
    <li className={DATA_ROW}>
      <ProjectMonogram name={p.name} />
      <div className="min-w-0 flex-1">
        <AppLink
          href={base}
          className="line-clamp-2 text-item font-semibold text-text-primary [overflow-wrap:anywhere] after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-accent"
        >
          {p.name}
        </AppLink>
        {p.description && (
          <p className="mt-0.5 line-clamp-1 text-ui text-text-secondary" title={p.description}>
            {p.description}
          </p>
        )}
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-text-secondary md:hidden">
          <span className="inline-flex items-center gap-1">
            <Files size={12} aria-hidden />
            {tn("documents.count", p.asset_count)}
          </span>
          <span className="inline-flex items-center gap-1">
            <Users size={12} aria-hidden />
            {tn("projects.memberCount", p.member_count)}
          </span>
        </p>
      </div>
      <dl className="hidden shrink-0 items-center gap-6 text-meta text-text-secondary md:flex">
        <div className="flex w-28 items-center gap-1.5">
          <dt className="sr-only">{t("projects.documentsLabel")}</dt>
          <Files size={14} aria-hidden />
          <dd className="tabular-nums">{tn("documents.count", p.asset_count)}</dd>
        </div>
        <div className="flex w-28 items-center gap-1.5">
          <dt className="sr-only">{t("projects.membersLabel")}</dt>
          <Users size={14} aria-hidden />
          <dd className="tabular-nums">{tn("projects.memberCount", p.member_count)}</dd>
        </div>
      </dl>
      <div className="relative z-10 flex shrink-0 items-center gap-2">
        <span className="hidden w-36 justify-end sm:flex">
          <ProjectRoleBadge role={p.my_role} />
        </span>
        <Menu
          label={t("projectRow.actions", { name: p.name })}
          actions={actions}
        />
      </div>
    </li>
  );
}

export const ProjectRow = memo(ProjectRowImpl);
