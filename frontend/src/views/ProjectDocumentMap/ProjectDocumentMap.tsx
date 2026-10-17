import { useCallback, useDeferredValue, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type Me, type RelationType } from "../../api";
import { ListFilter, Network, ShieldOff } from "lucide-react";
import { EmptyState } from "../../components/EmptyState";
import type { Density } from "../../components/graph";
import { ProjectFrame } from "../../components/projects/ProjectFrame";
import { SegmentedToggle } from "../../components/SegmentedToggle";
import { buttonClass } from "../../components/ui/Button";
import { Disclosure } from "../../components/ui/Disclosure";
import { Popover } from "../../components/ui/Popover";
import { formatApiError } from "../../lib/apiError";
import { t, tn } from "../../lib/i18n";
import { openInNewTab } from "../../lib/newTab";
import { qk } from "../../lib/queries";
import { useDocTypeLabel } from "../../lib/useDocTypes";
import { usePersistedChoice } from "../../lib/usePersistedChoice";
import { EMPTY_FILTERS, NO_DOC_TYPE, filterGraph, type MapFilters } from "./filters";
import { MapCanvas } from "./MapCanvas";
import { MapLegend } from "./MapLegend";
import { MapSidebar } from "./MapSidebar";
import { isTaskNodeId, type MapMode, type MapSceneInput } from "./model";
import { NodeList } from "./NodeList";
import { NodePanel } from "./NodePanel";
import { INPUT_CLASS } from "../../components/Field";

interface Props {
  me: Me;
  slug: string;
}

const NO_TASKS: never[] = [];
const DENSITIES: readonly Density[] = ["compact", "normal", "detailed"];

/** Map of a project's documents and their relations (ADR-0016). */
export function ProjectDocumentMap({ me, slug }: Props) {
  const typeLabel = useDocTypeLabel();
  const query = useQuery({
    queryKey: qk.projectGraph(slug),
    queryFn: () => api.getProjectGraph(slug, { tasks: true }),
  });
  const [filters, setFilters] = useState<MapFilters>(EMPTY_FILTERS);
  const [mode, setMode] = useState<MapMode>("graph");
  const [density, setDensity] = usePersistedChoice<Density>("ics-map-density", DENSITIES, "normal");
  const [showTasks, setShowTasks] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const graph = query.data ?? null;
  const tasks = graph?.tasks ?? NO_TASKS;
  const links = graph?.task_links ?? NO_TASKS;

  // Typing in the search box stays responsive: the map follows a render behind.
  const deferredFilters = useDeferredValue(filters);
  const filtered = useMemo(
    () => (graph ? filterGraph(graph, deferredFilters) : null),
    [graph, deferredFilters],
  );
  const sceneInput = useMemo<MapSceneInput | null>(
    () =>
      filtered
        ? {
            filtered,
            showUnlinked: deferredFilters.component === null,
            tasks,
            links,
            showTasks,
            mode,
            density,
            typeLabel,
          }
        : null,
    [filtered, deferredFilters.component, tasks, links, showTasks, mode, density, typeLabel],
  );
  const drawnRelations = useMemo(
    () => [...new Set((filtered?.edges ?? []).map((e) => e.relation_type))].sort(),
    [filtered],
  );
  const nodesById = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n])), [graph]);
  const present = useMemo(() => {
    const docTypes = new Set<string>();
    const relations = new Set<RelationType>();
    for (const n of graph?.nodes ?? []) docTypes.add(n.doc_type ?? NO_DOC_TYPE);
    for (const e of graph?.edges ?? []) relations.add(e.relation_type);
    return { docTypes: [...docTypes].sort(), relations: [...relations].sort() };
  }, [graph]);

  const onSelect = useCallback((id: string | null) => {
    // Task nodes have no panel of their own; their documents do.
    if (id === null || !isTaskNodeId(id)) setSelectedId(id);
  }, []);
  const onClose = useCallback(() => setSelectedId(null), []);
  const onOpenNewTab = useCallback(
    (id: string) => {
      const node = nodesById.get(id);
      if (node) openInNewTab(`/v/${node.slug}`);
    },
    [nodesById],
  );

  if (query.error) {
    return (
      <ProjectFrame me={me} slug={slug} tab="map">
        <EmptyState icon={ShieldOff} title={t("viewerStates.noAccess")} description={formatApiError(query.error)} />
      </ProjectFrame>
    );
  }

  if (!graph || !filtered || !sceneInput) {
    return (
      <ProjectFrame me={me} slug={slug} tab="map" width="full">
        <div className="skeleton h-[min(34rem,60dvh)] w-full rounded-card" aria-hidden />
        <p role="status" className="sr-only">
          {t("projectMap.loading")}
        </p>
      </ProjectFrame>
    );
  }

  const selected = selectedId ? nodesById.get(selectedId) : undefined;
  const canvasLabel = t("projectMap.canvasLabel", {
    nodes: filtered.nodes.length,
    edges: filtered.edges.length,
    graphs: filtered.componentSizes.length,
  });
  const hasCanvas = filtered.nodes.length > 0 || (sceneInput.showUnlinked && filtered.unlinked.length > 0);
  const activeFilters =
    filters.docTypes.size + filters.freshness.size + filters.relationTypes.size + (filters.search ? 1 : 0) + (filters.onlyTaskDocs ? 1 : 0);

  return (
    <ProjectFrame me={me} slug={slug} tab="map" width="full">
      <div role="toolbar" aria-label={t("projectMap.title")} className="mb-3 flex flex-wrap items-center gap-2">
        <SegmentedToggle<MapMode>
          value={mode}
          onChange={setMode}
          ariaLabel={t("projectMap.mode")}
          options={[
            { value: "graph", label: t("projectMap.modeGraph"), tooltip: t("projectMap.modeGraphHint") },
            { value: "trace", label: t("projectMap.modeTrace"), tooltip: t("projectMap.modeTraceHint") },
          ]}
        />
        <Popover
          label={t("projectMap.filters")}
          widthClass="w-[22rem]"
          trigger={(p) => (
            <button type="button" {...p} className={buttonClass("secondary")}>
              <ListFilter size={16} aria-hidden />
              {t("filters.title")}
              {activeFilters > 0 && (
                <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-caption font-semibold text-on-accent tabular-nums">
                  {activeFilters}
                </span>
              )}
            </button>
          )}
        >
          {() => (
            <MapSidebar
              filters={filters}
              onChange={setFilters}
              docTypes={present.docTypes}
              relationTypes={present.relations}
              hasTasks={tasks.length > 0}
              showTasks={showTasks}
              onShowTasks={setShowTasks}
            />
          )}
        </Popover>
        {filtered.componentSizes.length > 1 && (
          <label className="flex items-center gap-2 text-ui text-text-secondary">
            <span className="max-sm:sr-only">{t("projectMap.pickGraph")}</span>
            <select
              value={filters.component ?? ""}
              onChange={(e) => setFilters({ ...filters, component: e.target.value === "" ? null : Number(e.target.value) })}
              className={INPUT_CLASS}
            >
              <option value="">{t("projectMap.allGraphs", { count: filtered.componentSizes.length })}</option>
              {filtered.componentSizes.map((n, i) => (
                <option key={i} value={i}>
                  {t("projectMap.graphOption", { index: i + 1 })} · {tn("format.documentCount", n)}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="ml-auto">
          <MapLegend types={drawnRelations} tasks={showTasks && links.length > 0} />
        </div>
      </div>
      {graph.truncated && <p className="mb-3 text-meta text-text-secondary">{t("projectMap.truncated", { count: graph.max_nodes })}</p>}

      <div className="h-[calc(100dvh-22rem)] min-h-[26rem] overflow-hidden rounded-card border border-border bg-surface shadow-card">
        {hasCanvas ? (
          <MapCanvas
            input={sceneInput}
            selectedId={selectedId}
            onSelect={onSelect}
            onOpenNewTab={onOpenNewTab}
            onDensity={setDensity}
            label={canvasLabel}
            panel={
              selected && (
                <div className="w-[22rem] max-w-[45%] shrink-0 overflow-y-auto border-l border-border">
                  <NodePanel
                    node={selected}
                    nodesById={nodesById}
                    edges={graph.edges}
                    tasks={tasks}
                    links={links}
                    onSelect={onSelect}
                    onClose={onClose}
                  />
                </div>
              )
            }
          />
        ) : (
          <EmptyState icon={Network} framed={false} className="h-full" title={graph.nodes.length === 0 ? t("projectMap.empty") : t("projectMap.noEdges")} />
        )}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Disclosure title={t("projectMap.onMap", { count: filtered.nodes.length })}>
          <NodeList nodes={filtered.nodes} label={t("projectMap.onMapList")} selectedId={selectedId} onOpen={onSelect} />
        </Disclosure>
        {filtered.unlinked.length > 0 && (
          <Disclosure title={t("projectMap.unlinked", { count: filtered.unlinked.length })}>
            <NodeList nodes={filtered.unlinked} label={t("projectMap.unlinkedList")} selectedId={selectedId} onOpen={onSelect} />
          </Disclosure>
        )}
      </div>
    </ProjectFrame>
  );
}
