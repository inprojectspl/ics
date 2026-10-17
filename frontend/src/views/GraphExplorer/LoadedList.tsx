import { memo, useDeferredValue, useMemo, useState } from "react";
import { clsx } from "clsx";

import { SearchInput } from "../../components/SearchInput";
import { docTypeColor } from "../../components/graph";
import { t } from "../../lib/i18n";
import { matchesText } from "../../lib/text";
import { PROJECT_COLOR } from "./explorerScene";
import { itemTitle, type ExploredTree } from "./explorerTree";

// Rows have a fixed height, so the mounted window is plain arithmetic and
// needs no measuring (the same approach as the project map's node list).
const ROW_HEIGHT = 36;
/** Taller than the list ever gets, so the window always covers the visible rows. */
const VIEW_HEIGHT = 720;
const OVERSCAN = 8;

/** Indices of the rows to mount for a scroll position. */
export function windowOf(count: number, scrollTop: number): number[] {
  const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const last = Math.min(count - 1, Math.ceil((scrollTop + VIEW_HEIGHT) / ROW_HEIGHT) + OVERSCAN);
  const out: number[] = [];
  for (let i = first; i <= last; i++) out.push(i);
  return out;
}

interface Row {
  id: string;
  title: string;
  color: string;
  depth: number;
}

interface Props {
  tree: ExploredTree;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Ctrl/Cmd+click or a middle click on a row. */
  onOpenNewTab: (id: string) => void;
}

interface RowProps {
  row: Row;
  selected: boolean;
  onSelect: (id: string) => void;
  onOpenNewTab: (id: string) => void;
}

const ListRow = memo(function ListRow({ row, selected, onSelect, onOpenNewTab }: RowProps) {
  return (
    <button
      type="button"
      aria-current={selected || undefined}
      onClick={(e) => (e.ctrlKey || e.metaKey ? onOpenNewTab(row.id) : onSelect(row.id))}
      // A middle press would start autoscroll; its click opens a new tab.
      onMouseDown={(e) => {
        if (e.button === 1) e.preventDefault();
      }}
      onAuxClick={(e) => {
        if (e.button === 1) onOpenNewTab(row.id);
      }}
      className={clsx(
        "flex h-9 w-full items-center gap-2 rounded-control px-2 text-left text-ui",
        "text-text-secondary hover:bg-surface-hover hover:text-text-primary focus-visible:outline-2 focus-visible:outline-accent",
        selected && "bg-surface-hover text-text-primary",
      )}
    >
      <span aria-hidden className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: row.color }} />
      <span className="truncate">{row.title}</span>
    </button>
  );
});

/** Every card on the canvas in tree order, searchable; a click selects and frames the card. */
export function LoadedList({ tree, selectedId, onSelect, onOpenNewTab }: Props) {
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const [scrollTop, setScrollTop] = useState(0);

  const rows = useMemo(() => {
    const out: Row[] = [];
    const needle = deferred.trim();
    const walk = (id: string) => {
      const node = tree.nodes.get(id);
      if (!node) return;
      const item = node.item;
      if (item.kind !== "more") {
        const title = itemTitle(item);
        const hay = item.kind === "doc" ? `${title} ${item.slug}` : title;
        if (!needle || matchesText(hay, needle)) {
          out.push({ id, title, depth: node.depth, color: item.kind === "doc" ? docTypeColor(item.doc_type) : PROJECT_COLOR });
        }
      }
      for (const c of node.children) walk(c);
    };
    for (const r of tree.roots) walk(r);
    return out;
  }, [tree, deferred]);

  return (
    <section aria-label={t("graphExplorer.listTitle")} className="flex min-h-0 flex-1 flex-col px-3 pb-3 pt-2.5">
      <h3 className="mb-1.5 px-1 text-meta font-medium text-text-secondary">{t("graphExplorer.listTitle")}</h3>
      <SearchInput
        value={query}
        onChange={setQuery}
        ariaLabel={t("graphExplorer.listSearch")}
        placeholder={t("graphExplorer.listSearch")}
        className="mb-2"
      />
      {rows.length === 0 ? (
        <p className="px-2 py-3 text-ui text-text-tertiary">{t("graphExplorer.listEmpty")}</p>
      ) : (
        <div onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)} className="min-h-40 flex-1 overflow-y-auto">
          <ul className="relative" style={{ height: rows.length * ROW_HEIGHT }}>
            {windowOf(rows.length, scrollTop).map((index) => {
              const row = rows[index];
              if (!row) return null;
              return (
                <li key={row.id} className="absolute left-0 right-0" style={{ top: index * ROW_HEIGHT, height: ROW_HEIGHT, paddingLeft: Math.min(row.depth, 6) * 12 }}>
                  <ListRow row={row} selected={row.id === selectedId} onSelect={onSelect} onOpenNewTab={onOpenNewTab} />
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}
