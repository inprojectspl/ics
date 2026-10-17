import { useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Files, Users } from "lucide-react";
import type { Me, ProjectSummary } from "../../api";
import { t, tn } from "../../lib/i18n";
import { projectListQuery } from "../../lib/queries";
import { rememberProject } from "../../lib/recentProjects";
import { PROJECT_TAB_LABEL, ProjectTabs, type ProjectTab } from "../ProjectTabs";
import { Page } from "../shell/Page";
import { PageContext } from "../shell/PageContext";
import { PageHeader } from "../ui/PageHeader";
import { ProjectMonogram } from "./ProjectMonogram";
import { ProjectRoleBadge } from "./ProjectRoleBadge";

interface Props {
  me: Me;
  slug: string;
  tab: ProjectTab;
  /** Header actions of the project (upload, invite, the `…` menu). */
  actions?: ReactNode;
  /** Location-bound actions in the breadcrumb bar (watching). */
  contextActions?: ReactNode;
  /** The document map needs the whole width. */
  width?: "content" | "full";
  children: ReactNode;
}

const NO_PROJECTS: ProjectSummary[] = [];

/**
 * Frame of every project page: the breadcrumb, one heading with the role
 * and the size of the project, the project's local tabs, then the tab.
 * The summary comes from the project list the sidebar already holds.
 */
export function ProjectFrame({ me, slug, tab, actions, contextActions, width = "content", children }: Props) {
  const projects =
    useQuery({
      ...projectListQuery,
    }).data ?? NO_PROJECTS;
  const project = projects.find((p) => p.slug === slug) ?? null;
  const admin = me.role === "admin";
  const role = project?.my_role ?? null;

  useEffect(() => {
    if (project) rememberProject(slug);
  }, [project, slug]);

  const name = project?.name ?? t("projectDetail.loadingTitle");
  const base = `/projects/${slug}`;
  const crumbs = [
    { label: t("nav.projects"), href: "/projects" },
    tab === "files" ? { label: name } : { label: name, href: base },
    ...(tab === "files" ? [] : [{ label: t(PROJECT_TAB_LABEL[tab]) }]),
  ];

  return (
    <>
      <PageContext crumbs={crumbs} actions={contextActions} activeHref={base} />
      <Page width={width === "full" ? "full" : "content"}>
        <PageHeader
          className="mb-0"
          leading={<ProjectMonogram name={name} size="lg" />}
          title={name}
          description={
            project ? (
              <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <ProjectRoleBadge role={role} />
                <span className="inline-flex items-center gap-1 text-meta">
                  <Files size={13} aria-hidden />
                  {tn("documents.count", project.asset_count)}
                </span>
                <span className="inline-flex items-center gap-1 text-meta">
                  <Users size={13} aria-hidden />
                  {tn("projects.memberCount", project.member_count)}
                </span>
              </span>
            ) : (
              " "
            )
          }
          actions={actions}
        />
        {project?.description && tab === "files" && (
          <p className="mt-3 max-w-3xl text-body text-text-secondary [overflow-wrap:anywhere]">{project.description}</p>
        )}
        <ProjectTabs
          slug={slug}
          tab={tab}
          member={role !== null || admin}
          canMaintain={admin || role === "owner" || role === "editor"}
          isOwner={admin || role === "owner"}
        />
        <div className="mt-6">{children}</div>
      </Page>
    </>
  );
}
