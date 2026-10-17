import { memo, useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";

import type { ProjectGraphNode } from "../../api/types";
import { docTypeColor } from "../../components/graph";
import { t } from "../../lib/i18n";

// Above this many rows only the visible ones are mounted. Rows have a fixed
// height, so the window is plain arithmetic and needs no measuring.
const VIRTUAL_FROM = 200;
const ROW_HEIGHT = 36;
const VIEW_HEIGHT = 320;
const OVERSCAN = 8;

interface Props {
  nodes: ProjectGraphNode[];
  label: string;
  selectedId: string | null;
  onOpen: (id: string) => void;
}

interface RowProps {
  node: ProjectGraphNode;
  index: number;
  active: boolean;
  selected: boolean;
  onOpen: (id: string) => void;
  onFocusRow: (index: number) => void;
}

const NodeRow = memo(function NodeRow({ node, index, active, selected, onOpen, onFocusRow }: RowProps) {
  return (
    <button
      type="button"
      data-index={index}
      tabIndex={active ? 0 : -1}
      aria-current={selected || undefined}
      onClick={() => onOpen(node.id)}
      onFocus={() => onFocusRow(index)}
      className={clsx(
        "flex w-full items-center gap-2 px-2 h-9 rounded-control text-left text-ui",
        "text-text-secondary hover:text-text-primary hover:bg-text-primary/[0.035] focus-visible:outline-2 focus-visible:outline-accent",
        selected && "bg-text-primary/[0.05] text-text-primary",
      )}
    >
      <span
        aria-hidden
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: docTypeColor(node.doc_type) }}
      />
      <span className="truncate">{node.title || node.slug}</span>
      {node.external && (
        <span className="ml-auto shrink-0 text-meta text-text-tertiary">{t("projectMap.external")}</span>
      )}
    </button>
  );
});

/** Indices of the rows to mount for a scroll position, with overscan. */
function windowOf(count: number, scrollTop: number): number[] {
  const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const last = Math.min(count - 1, Math.ceil((scrollTop + VIEW_HEIGHT) / ROW_HEIGHT) + OVERSCAN);
  const out: number[] = [];
  for (let i = first; i <= last; i++) out.push(i);
  return out;
}

/**
 * Keyboard-reachable list of the map's documents: one tab stop, arrows move
 * between rows, Enter or Space opens the node panel.
 */
export function NodeList({ nodes, label, selectedId, onOpen }: Props) {
  const [active, setActive] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);
  const wantsFocus = useRef(false);
  const virtual = nodes.length > VIRTUAL_FROM;
  const current = Math.min(active, Math.max(0, nodes.length - 1));

  useEffect(() => {
    if (!wantsFocus.current) return;
    wantsFocus.current = false;
    listRef.current?.querySelector<HTMLElement>(`[data-index="${current}"]`)?.focus();
  }, [current]);

  const onFocusRow = useCallback((index: number) => setActive(index), []);

  /** Scrolls the window so row `index` is mounted and visible. */
  const reveal = (index: number) => {
    const el = listRef.current;
    if (!virtual || !el) return;
    const top = index * ROW_HEIGHT;
    let next = el.scrollTop;
    if (top < next) next = top;
    else if (top + ROW_HEIGHT > next + VIEW_HEIGHT) next = top + ROW_HEIGHT - VIEW_HEIGHT;
    el.scrollTop = next;
    setScrollTop(next);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const last = nodes.length - 1;
    let next: number | null = null;
    if (e.key === "ArrowDown") next = Math.min(last, current + 1);
    else if (e.key === "ArrowUp") next = Math.max(0, current - 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    else if (e.key === "Enter" || e.key === " ") {
      const node = nodes[current];
      if (node) {
        e.preventDefault();
        onOpen(node.id);
      }
      return;
    }
    if (next === null || last < 0) return;
    e.preventDefault();
    wantsFocus.current = true;
    reveal(next);
    setActive(next);
  };

  if (nodes.length === 0) return null;

  const row = (node: ProjectGraphNode, index: number) => (
    <NodeRow
      node={node}
      index={index}
      active={index === current}
      selected={node.id === selectedId}
      onOpen={onOpen}
      onFocusRow={onFocusRow}
    />
  );

  return (
    <div
      ref={listRef}
      role="list"
      aria-label={label}
      onKeyDown={onKeyDown}
      onScroll={virtual ? (e) => setScrollTop(e.currentTarget.scrollTop) : undefined}
      className="max-h-80 overflow-y-auto"
    >
      {virtual ? (
        <div className="relative" style={{ height: nodes.length * ROW_HEIGHT }}>
          {windowOf(nodes.length, scrollTop).map((index) => {
            const node = nodes[index];
            if (!node) return null;
            return (
              <div
                key={node.id}
                role="listitem"
                className="absolute left-0 right-0"
                style={{ top: index * ROW_HEIGHT, height: ROW_HEIGHT }}
              >
                {row(node, index)}
              </div>
            );
          })}
        </div>
      ) : (
        nodes.map((node, index) => (
          <div key={node.id} role="listitem">
            {row(node, index)}
          </div>
        ))
      )}
    </div>
  );
}
