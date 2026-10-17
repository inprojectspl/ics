import { useId, useMemo, useRef, useState } from "react";
import { clsx } from "clsx";
import { Network } from "lucide-react";

import { SearchInput } from "../../components/SearchInput";
import { useOverlay } from "../../components/ui/useOverlay";
import { t, type MessageKey } from "../../lib/i18n";
import { matchesText } from "../../lib/text";
import { canSearchDocuments, useDocumentSearch } from "../../lib/useDocumentSearch";
import type { ExploredTree } from "./explorerTree";
import type { WalkTarget } from "./useExplorer";

interface Props {
  tree: ExploredTree;
  /** A walk to a picked result is loading. */
  walking: boolean;
  onPick: (target: WalkTarget) => void;
}

/** Id of the search input, for the `/` shortcut. */
export const SEARCH_ID = "graph-explorer-search";
const SERVER_LIMIT = 8;
const LOCAL_LIMIT = 5;

interface Option extends WalkTarget {
  group: MessageKey;
}

/**
 * Search over the whole graph the reader can open, not only the loaded
 * cards: cards on the canvas first, then documents found in ICS. Picking
 * one walks the graph to it instead of starting a new graph.
 */
export function GraphSearch({ tree, walking, onPick }: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const listId = useId();
  const q = query.trim();
  const server = useDocumentSearch(q, SERVER_LIMIT);

  const options = useMemo<Option[]>(() => {
    if (!canSearchDocuments(q)) return [];
    const out: Option[] = [];
    const seen = new Set<string>();
    for (const n of tree.nodes.values()) {
      if (out.length >= LOCAL_LIMIT) break;
      const item = n.item;
      if (item.kind !== "doc" || !matchesText(item.title ?? item.slug, q)) continue;
      out.push({ id: item.id, slug: item.slug, title: item.title, group: "graphExplorer.searchOnCanvas" });
      seen.add(item.id);
    }
    for (const a of server.data ?? []) {
      if (seen.has(a.id)) continue;
      out.push({ id: a.id, slug: a.slug, title: a.title, group: "graphExplorer.searchInIcs" });
    }
    return out;
  }, [q, tree, server.data]);

  const shown = open && canSearchDocuments(q);
  const active = Math.min(cursor, Math.max(0, options.length - 1));
  const close = () => setOpen(false);
  useOverlay(wrapRef, shown, { onClose: close, keepFocus: true });

  const pick = (o: Option | undefined) => {
    if (!o) return;
    onPick({ id: o.id, slug: o.slug, title: o.title });
    setQuery("");
    setOpen(false);
  };
  const searching = server.isSearching;

  let lastGroup: MessageKey | null = null;
  return (
    <div
      ref={wrapRef}
      className="relative w-full sm:w-80"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) close();
      }}
    >
      <SearchInput
        value={query}
        onChange={(v) => {
          setQuery(v);
          setCursor(0);
          setOpen(true);
        }}
        busy={walking || (shown && searching)}
        ariaLabel={t("graphExplorer.search")}
        placeholder={t("graphExplorer.searchPlaceholder")}
        inputProps={{
          id: SEARCH_ID,
          maxLength: 200,
          role: "combobox",
          "aria-expanded": shown,
          "aria-controls": listId,
          "aria-autocomplete": "list",
          "aria-activedescendant": shown && options.length ? `${listId}-${active}` : undefined,
          onFocus: () => setOpen(true),
          onKeyDown: (e) => {
            if (e.key === "ArrowDown") setCursor(Math.min(active + 1, options.length - 1));
            else if (e.key === "ArrowUp") setCursor(Math.max(active - 1, 0));
            else if (e.key === "Enter") pick(options[active]);
            else return;
            e.preventDefault();
          },
        }}
      />
      {shown && (
        <ul
          id={listId}
          role="listbox"
          aria-label={t("graphExplorer.searchResults")}
          className="absolute left-0 top-full z-30 mt-1 max-h-[min(24rem,60dvh)] w-full min-w-72 overflow-y-auto rounded-card border border-border bg-surface py-1.5 shadow-floating"
        >
          {server.error && <li role="presentation" className="px-4 py-3 text-ui text-text-secondary">
            <p role="alert">{t("home.searchFailed")}</p>
          </li>}
          {options.length === 0 ? !server.error && (
            <li role="presentation" className="px-4 py-3 text-ui text-text-secondary">
              {t(searching ? "palette.searching" : "graphExplorer.searchEmpty")}
            </li>
          ) : (
            options.flatMap((o, i) => {
              const rows = [];
              if (o.group !== lastGroup) {
                lastGroup = o.group;
                rows.push(
                  <li key={`h:${o.group}`} role="presentation" className="px-3 pb-1 pt-2 text-meta font-medium text-text-secondary">
                    {t(o.group)}
                  </li>,
                );
              }
              rows.push(
                <li
                  key={o.id}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onPointerMove={() => setCursor(i)}
                  // Keeps the input focused, so the blur does not close the list before the click.
                  onPointerDown={(e) => e.preventDefault()}
                  onClick={() => pick(o)}
                  className={clsx(
                    "mx-1.5 flex cursor-pointer items-center gap-2.5 rounded-control px-2.5 py-2 text-ui text-text-primary",
                    i === active && "bg-accent-soft",
                  )}
                >
                  <Network size={14} aria-hidden className={clsx("shrink-0", i === active ? "text-accent" : "text-text-tertiary")} />
                  <span className="min-w-0 flex-1 truncate">{o.title || o.slug}</span>
                </li>,
              );
              return rows;
            })
          )}
        </ul>
      )}
    </div>
  );
}
