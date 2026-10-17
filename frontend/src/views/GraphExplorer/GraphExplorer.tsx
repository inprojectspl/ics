import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FolderKanban, ShieldOff } from "lucide-react";

import { RELATION_TYPES, type RelationType } from "../../api/relationTypes";
import { EmptyState } from "../../components/EmptyState";
import { Page } from "../../components/shell/Page";
import { useShell } from "../../components/shell/shellContext";
import { PageContext } from "../../components/shell/PageContext";
import { AppLink } from "../../components/ui/AppLink";
import { buttonClass } from "../../components/ui/Button";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { graphHref } from "../../lib/graphHref";
import { projectListQuery } from "../../lib/queries";
import { ExplorerBody } from "./ExplorerBody";
import { projectItem, rootItem, sourceQuery } from "./explorerData";
import type { Expansion, ExplorerItem } from "./explorerTree";

interface Props {
  /** Slug of the document to start from; without it the roots are the projects. */
  doc?: string;
}

const ALL_TYPES: ReadonlySet<RelationType> = new Set(RELATION_TYPES);
const NO_EXPANSIONS: Expansion[] = [];

function Frame({ title, description, docSlug, children }: { title: string; description: string; docSlug?: string; children: React.ReactNode }) {
  const crumbs = docSlug
    ? [{ label: t("graphExplorer.title"), href: graphHref() }, { label: title }]
    : [{ label: t("graphExplorer.title") }];
  // In focus the graph takes the page: the breadcrumbs still say where it is.
  const { focusMode } = useShell();
  return (
    <>
      <PageContext crumbs={crumbs} activeHref={graphHref()} />
      <Page width="full">
        {!focusMode && (
          <PageHeader
            title={title}
            description={description}
            actions={
              docSlug && (
                <AppLink href={`/v/${docSlug}`} className={buttonClass("secondary")}>
                  {t("graphExplorer.openDocument")}
                </AppLink>
              )
            }
            className="mb-4"
          />
        )}
        {children}
      </Page>
    </>
  );
}

function Loading() {
  return (
    <>
      <div className="skeleton h-[min(34rem,60dvh)] w-full rounded-card" aria-hidden />
      <p role="status" className="sr-only">
        {t("graphExplorer.loading")}
      </p>
    </>
  );
}

/** The graph explorer: a walk from the user's projects, or from one document (`?doc=`). */
export function GraphExplorer({ doc }: Props) {
  // A new start point is a new walk.
  return doc ? <DocumentExplorer key={doc} slug={doc} /> : <ProjectsExplorer />;
}

function useTypes() {
  return useState<ReadonlySet<RelationType>>(ALL_TYPES);
}

function ProjectsExplorer() {
  const query = useQuery(projectListQuery);
  const [types, setTypes] = useTypes();
  const roots = useMemo<ExplorerItem[]>(() => (query.data ?? []).map(projectItem), [query.data]);
  const title = t("graphExplorer.title");
  const description = t("graphExplorer.description");
  if (query.error) {
    return (
      <Frame title={title} description={description}>
        <EmptyState icon={ShieldOff} title={t("viewerStates.noAccess")} description={formatApiError(query.error)} />
      </Frame>
    );
  }
  if (!query.data) {
    return (
      <Frame title={title} description={description}>
        <Loading />
      </Frame>
    );
  }
  return (
    <Frame title={title} description={description}>
      {roots.length === 0 ? (
        <EmptyState icon={FolderKanban} title={t("graphExplorer.noProjects")} description={t("graphExplorer.noProjectsHint")} />
      ) : (
        <ExplorerBody roots={roots} initial={NO_EXPANSIONS} types={types} onTypes={setTypes} />
      )}
    </Frame>
  );
}

function DocumentExplorer({ slug }: { slug: string }) {
  const query = useQuery(sourceQuery({ kind: "doc", slug }));
  const [types, setTypes] = useTypes();
  const root = useMemo(() => rootItem(query.data), [query.data]);
  const roots = useMemo<ExplorerItem[]>(() => (root ? [root] : []), [root]);
  // The start document opens one level deep.
  const initial = useMemo<Expansion[]>(() => (root ? [{ id: root.id, source: { kind: "doc", slug } }] : []), [root, slug]);
  const description = t("graphExplorer.docDescription");
  if (query.error) {
    return (
      <Frame title={t("graphExplorer.title")} description={description} docSlug={slug}>
        <EmptyState icon={ShieldOff} title={t("viewerStates.noAccess")} description={formatApiError(query.error)} />
      </Frame>
    );
  }
  if (!root) {
    return (
      <Frame title={t("graphExplorer.title")} description={description} docSlug={slug}>
        <Loading />
      </Frame>
    );
  }
  return (
    <Frame title={root.title || root.slug} description={description} docSlug={slug}>
      <ExplorerBody roots={roots} initial={initial} types={types} onTypes={setTypes} />
    </Frame>
  );
}
