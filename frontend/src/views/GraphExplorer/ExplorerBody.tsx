import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clsx } from "clsx";
import { Maximize2, Minimize2, X } from "lucide-react";

import type { RelationType } from "../../api/relationTypes";
import { CARD_SIZES, CardCanvas, useMeasured, type Density, type Size } from "../../components/graph";
import type { Direction } from "../../components/graph/cardTypes";
import { RelationLegend } from "../../components/graph/RelationLegend";
import { SegmentedToggle } from "../../components/SegmentedToggle";
import { useShell } from "../../components/shell/shellContext";
import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { Sheet } from "../../components/ui/Sheet";
import { overlayOpen } from "../../components/ui/useOverlay";
import { t, tn } from "../../lib/i18n";
import { graphHref } from "../../lib/graphHref";
import { navigate } from "../../lib/navigate";
import { ownsKey } from "../../lib/keyboard";
import { openInNewTab } from "../../lib/newTab";
import { useDocTypeLabel } from "../../lib/useDocTypes";
import { MOBILE_QUERY, useMediaQuery } from "../../lib/useMediaQuery";
import { usePersistedChoice } from "../../lib/usePersistedChoice";
import { ExplorerPanel } from "./ExplorerPanel";
import { buildScene } from "./explorerScene";
import { itemHref, itemTitle, type Expansion, type ExplorerItem } from "./explorerTree";
import { FloatingPanel, PANEL_INSET } from "./FloatingPanel";
import { GraphSearch, SEARCH_ID } from "./GraphSearch";
import { ShortcutsHelp } from "./ShortcutsHelp";
import { LoadedList } from "./LoadedList";
import { WRAP, wrapFor } from "./treeLayout";
import { RelationFilter } from "./RelationFilter";
import { useExplorer, type WalkTarget } from "./useExplorer";

interface Props {
  roots: readonly ExplorerItem[];
  initial: Expansion[];
  types: ReadonlySet<RelationType>;
  onTypes: (next: ReadonlySet<RelationType>) => void;
}

const DENSITIES: readonly Density[] = ["compact", "normal"];
const DIRECTIONS: readonly Direction[] = ["down", "right"];
const PANEL_STATES = ["open", "minimized"] as const;

/** The one notice over the canvas: a failed load, then an unreachable search result, then folded branches. */
function noticeOf(error: string | null, unreachable: WalkTarget | null, evicted: number): string | null {
  if (error) return t("graphExplorer.loadFailed", { error });
  if (unreachable) return t("graphExplorer.unreachable", { title: unreachable.title || unreachable.slug });
  if (evicted > 0) return t("graphExplorer.evicted", { count: evicted });
  return null;
}

/** Canvas, toolbar and side panel of one walk through the graph. */
export function ExplorerBody({ roots, initial, types, onTypes }: Props) {
  const typeLabel = useDocTypeLabel();
  const phone = useMediaQuery(MOBILE_QUERY);
  const [density, setDensity] = usePersistedChoice<Density>("ics-explorer-density", DENSITIES, "normal");
  // Top down by default: siblings side by side use a wide screen better than a tall column.
  const [direction, setDirection] = usePersistedChoice<Direction>("ics-explorer-direction", DIRECTIONS, "down");
  const [panelState, setPanelState] = usePersistedChoice("ics-explorer-panel", PANEL_STATES, "open");
  const [sheetOpen, setSheetOpen] = useState(false);
  const { focusMode, setFocusMode } = useShell();
  // Focus belongs to this page: leaving it gives the sidebar and the header back.
  useEffect(() => () => setFocusMode(false), [setFocusMode]);
  const x = useExplorer(roots, initial, types);
  const { tree, pending } = x;

  const boxRef = useRef<HTMLDivElement | null>(null);
  const panelInset = !phone && panelState === "open" ? PANEL_INSET : 0;
  const deriveWrap = useCallback(
    (box: Size) => wrapFor(direction, { w: box.w - panelInset, h: box.h }, CARD_SIZES[density]),
    [direction, panelInset, density],
  );
  const wrap = useMeasured(boxRef, deriveWrap, WRAP);
  const scene = useMemo(
    () => buildScene({ tree, density, direction, wrap, typeLabel, pending }),
    [tree, density, direction, wrap, typeLabel, pending],
  );
  const docCount = useMemo(() => {
    let n = 0;
    for (const node of tree.nodes.values()) if (node.item.kind === "doc") n++;
    return n;
  }, [tree]);
  const drawn = useMemo(() => {
    const set = new Set<RelationType>();
    for (const e of tree.edges) if (e.relation) set.add(e.relation.relation_type);
    return [...set].sort();
  }, [tree]);

  const selectedNode = x.selectedId ? tree.nodes.get(x.selectedId) : undefined;
  const selectedTitle = selectedNode && selectedNode.item.kind !== "more" ? itemTitle(selectedNode.item) : null;

  const onReroot = useCallback((slug: string) => navigate(graphHref(slug)), []);
  const onOpenNewTab = useCallback(
    (id: string) => {
      const item = tree.nodes.get(id)?.item;
      if (item && item.kind !== "more") openInNewTab(itemHref(item));
    },
    [tree],
  );

  // Shortcuts act on the canvas and the selection, never while a field or an overlay has the keys.
  const { expandNode, collapseNode } = x;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (ownsKey(e.target, e.key) || e.defaultPrevented || e.altKey || overlayOpen()) return;
      const mod = e.ctrlKey || e.metaKey;
      const item = selectedNode?.item;
      const card = item && item.kind !== "more" ? item : null;
      if (e.key === "Enter" && card) {
        if (mod) openInNewTab(itemHref(card));
        else navigate(itemHref(card));
      } else if (mod) {
        return;
      } else if (e.key === "/") {
        document.getElementById(SEARCH_ID)?.focus();
      } else if ((e.key === "e" || e.key === " ") && card && selectedNode) {
        if (selectedNode.expanded) collapseNode(card.id);
        else expandNode(card.id);
      } else if (e.key === "f") {
        setFocusMode(!focusMode);
      } else if (e.key === "p" && !phone) {
        setPanelState(panelState === "open" ? "minimized" : "open");
      } else {
        return;
      }
      e.preventDefault();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [selectedNode, expandNode, collapseNode, focusMode, setFocusMode, phone, panelState, setPanelState]);
  const closeSheet = useCallback(() => setSheetOpen(false), []);

  const panel = (
    <ExplorerPanel
      tree={tree}
      selectedId={x.selectedId}
      pending={pending}
      onSelect={x.select}
      onExpand={x.expandNode}
      onCollapse={x.collapseNode}
      onReroot={onReroot}
    >
      <LoadedList tree={tree} selectedId={x.selectedId} onSelect={x.select} onOpenNewTab={onOpenNewTab} />
    </ExplorerPanel>
  );
  const unreachable = x.unreachable;
  const notice = noticeOf(x.error, unreachable, x.evicted);

  return (
    <>
      <div role="toolbar" aria-label={t("graphExplorer.title")} className="mb-3 flex flex-wrap items-center gap-2">
        <GraphSearch tree={tree} walking={x.walking} onPick={x.goTo} />
        <RelationFilter types={types} onChange={onTypes} />
        <span role="status" className="text-meta tabular-nums text-text-secondary">
          {docCount > 0 && tn("graphExplorer.loadedCount", docCount)}
        </span>
        {phone && (
          <Button variant="secondary" size="sm" onClick={() => setSheetOpen(true)}>
            {t("graphExplorer.panelButton")}
          </Button>
        )}
        <div className="ml-auto flex items-center gap-3">
          <RelationLegend types={drawn} />
          <ShortcutsHelp />
          <IconButton
            size="sm"
            label={t(focusMode ? "graphExplorer.focusOff" : "graphExplorer.focusOn")}
            aria-pressed={focusMode}
            icon={focusMode ? <Minimize2 size={16} aria-hidden /> : <Maximize2 size={16} aria-hidden />}
            onClick={() => setFocusMode(!focusMode)}
          />
        </div>
      </div>
      {notice && (
        <div className="mb-3 flex items-center gap-2 rounded-card border border-border bg-surface px-3 py-1.5 text-meta text-text-secondary">
          <p role="alert" className="flex-1">
            {notice}
          </p>
          {unreachable && !x.error && (
            <Button variant="secondary" size="sm" onClick={() => onReroot(unreachable.slug)}>
              {t("graphExplorer.showFromHere")}
            </Button>
          )}
          <IconButton label={t("common.close")} icon={<X size={14} aria-hidden />} onClick={x.dismissNotice} noTooltip />
        </div>
      )}
      <div
        ref={boxRef}
        className={clsx(
          "relative min-h-[26rem] overflow-hidden rounded-card border border-border bg-surface shadow-card",
          // Focus: the canvas takes the screen under the global bar, the breadcrumbs and the toolbar.
          focusMode ? "h-[calc(100dvh-var(--topbar-height)-8.5rem)]" : "h-[calc(100dvh-17rem)]",
        )}
      >
        <CardCanvas
          scene={scene}
          selectedId={x.selectedId}
          onSelect={x.select}
          onOpenNewTab={onOpenNewTab}
          fitInsetRight={panelInset}
          label={t("graphExplorer.canvasLabel", { cards: scene.cards.length, edges: scene.edges.length })}
          toolbarExtra={
            <>
              <SegmentedToggle<Direction>
                value={direction}
                onChange={setDirection}
                ariaLabel={t("graphExplorer.direction")}
                options={[
                  { value: "down", label: t("graphExplorer.directionDown"), tooltip: t("graphExplorer.directionDownHint") },
                  { value: "right", label: t("graphExplorer.directionRight"), tooltip: t("graphExplorer.directionRightHint") },
                ]}
              />
              <SegmentedToggle<Density>
                value={density}
                onChange={setDensity}
                ariaLabel={t("cardGraph.density")}
                options={[
                  { value: "compact", label: t("cardGraph.densityCompact") },
                  { value: "normal", label: t("cardGraph.densityNormal") },
                ]}
              />
            </>
          }
        />
        {!phone && (
          <FloatingPanel
            open={panelState === "open"}
            onOpenChange={(open) => setPanelState(open ? "open" : "minimized")}
            selected={selectedTitle}
          >
            {panel}
          </FloatingPanel>
        )}
      </div>
      {phone && (
        <Sheet open={sheetOpen} title={t("graphExplorer.panelButton")} onClose={closeSheet}>
          {panel}
        </Sheet>
      )}
    </>
  );
}
