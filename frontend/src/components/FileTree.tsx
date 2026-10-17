import { useMemo, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { Trash2 } from "lucide-react";
import { getLocale, t } from "../lib/i18n";

const DRAG_TYPE = "text/x-ics-file-path";

interface Props {
  paths: string[];
  current: string;
  onSelect: (path: string) => void;
  /**
   * The vault hides `.md` (file name equals note title), but the comparison
   * screen shows full names, where `index.html` and `app.css` differ exactly
   * by extension. The default keeps the vault behaviour.
   */
  stripExtension?: boolean;
  /**
   * Marker to the left of the name (on the diff screen: `+` / `-` / `~`).
   * Return `null` to leave the row unmarked.
   */
  badgeFor?: (path: string) => ReactNode;
  /** Editor and up (the backend's min role): when provided, a hover-only
   * trash icon appears next to each file. */
  onDelete?: (path: string) => void;
  /** Editor and up: when provided, files become draggable and folder rows
   * (plus the synthetic root row above the tree) become drop targets.
   * `toFolder` is the folder path the file was dropped on, with `""`
   * meaning the collection root. */
  onMove?: (fromPath: string, toFolder: string) => void;
}

interface Node {
  name: string;
  path: string;
  children: Map<string, Node>;
  isFile: boolean;
}

function buildTree(paths: string[]): Node {
  const root: Node = { name: "", path: "", children: new Map(), isFile: false };
  for (const p of paths) {
    const parts = p.split("/").filter(Boolean);
    let cur = root;
    let acc = "";
    parts.forEach((part, i) => {
      acc = acc ? `${acc}/${part}` : part;
      let next = cur.children.get(part);
      if (!next) {
        next = {
          name: part,
          path: acc,
          children: new Map(),
          isFile: i === parts.length - 1,
        };
        cur.children.set(part, next);
      }
      cur = next;
    });
  }
  return root;
}

function sortChildren(node: Node, filesFirst = false): Node[] {
  return Array.from(node.children.values()).sort((a, b) => {
    if (a.isFile !== b.isFile) {
      // Folders first, except at the root: a file dropped there would
      // otherwise render below every subfolder and look as if it never landed.
      if (filesFirst) return a.isFile ? -1 : 1;
      return a.isFile ? 1 : -1;
    }
    return a.name.localeCompare(b.name, getLocale());
  });
}

function folderOf(path: string): string {
  const i = path.lastIndexOf("/");
  return i < 0 ? "" : path.slice(0, i);
}

export function FileTree({
  paths,
  current,
  onSelect,
  stripExtension = true,
  badgeFor,
  onDelete,
  onMove,
}: Props) {
  const root = useMemo(() => buildTree(paths), [paths]);
  return (
    <nav aria-label={t("fileTree.label")} className="text-ui">
      <TreeLevel
        nodes={sortChildren(root, true)}
        depth={0}
        current={current}
        onSelect={onSelect}
        stripExtension={stripExtension}
        badgeFor={badgeFor}
        onDelete={onDelete}
        onMove={onMove}
      />
    </nav>
  );
}

interface LevelProps {
  nodes: Node[];
  depth: number;
  current: string;
  onSelect: (path: string) => void;
  stripExtension: boolean;
  badgeFor?: (path: string) => ReactNode;
  onDelete?: (path: string) => void;
  onMove?: (fromPath: string, toFolder: string) => void;
}

function TreeLevel({
  nodes,
  depth,
  current,
  onSelect,
  stripExtension,
  badgeFor,
  onDelete,
  onMove,
}: LevelProps) {
  return (
    <ul className="space-y-0.5">
      {nodes.map((n) => (
        <TreeItem
          key={n.path}
          node={n}
          depth={depth}
          current={current}
          onSelect={onSelect}
          stripExtension={stripExtension}
          badgeFor={badgeFor}
          onDelete={onDelete}
          onMove={onMove}
        />
      ))}
    </ul>
  );
}

function TreeItem({
  node,
  depth,
  current,
  onSelect,
  stripExtension,
  badgeFor,
  onDelete,
  onMove,
}: {
  node: Node;
  depth: number;
  current: string;
  onSelect: (path: string) => void;
  stripExtension: boolean;
  badgeFor?: (path: string) => ReactNode;
  onDelete?: (path: string) => void;
  onMove?: (fromPath: string, toFolder: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const [dragOver, setDragOver] = useState(false);
  const indent = { paddingLeft: `${depth * 0.9}rem` };

  if (node.isFile) {
    const label = stripExtension ? node.name.replace(/\.md$/i, "") : node.name;
    const isCurrent = node.path === current;
    return (
      <li className="group/file relative">
        <button
          type="button"
          onClick={() => onSelect(node.path)}
          draggable={Boolean(onMove)}
          onDragStart={(e) => {
            if (!onMove) return;
            e.dataTransfer.setData(DRAG_TYPE, node.path);
            e.dataTransfer.effectAllowed = "move";
          }}
          style={indent}
          className={clsx(
            "block w-full text-left py-1 pl-2 pr-7 rounded-control truncate cursor-pointer",
            onMove && "active:cursor-grabbing",
            isCurrent
              ? "bg-accent-soft text-accent"
              : "text-text-secondary hover:bg-surface-subtle hover:text-text-primary",
          )}
        >
          {badgeFor && (
            <span aria-hidden className="inline-block w-3 mr-1 font-code">
              {badgeFor(node.path)}
            </span>
          )}
          {label}
        </button>
        {onDelete && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(node.path);
            }}
            aria-label={t("fileTree.deleteLabel", { name: label })}
            title={t("fileTree.deleteTitle")}
            className={clsx(
              "absolute right-1 top-1/2 -translate-y-1/2",
              "inline-flex items-center justify-center min-w-9 min-h-9 p-2 rounded-control",
              // On mobile (no hover state) keep the action visible at low
              // opacity; on desktop reveal fully on row hover.
              "opacity-60 lg:opacity-0 lg:group-hover/file:opacity-100 focus-visible:opacity-100",
              "text-text-tertiary hover:text-danger hover:bg-danger/10 transition-opacity",
            )}
          >
            <Trash2 size={13} aria-hidden />
          </button>
        )}
      </li>
    );
  }

  const acceptDrop = Boolean(onMove);
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        onDragOver={(e) => {
          if (!acceptDrop) return;
          if (!e.dataTransfer.types.includes(DRAG_TYPE)) return;
          e.preventDefault();
          e.stopPropagation();
          e.dataTransfer.dropEffect = "move";
          setDragOver(true);
        }}
        onDragLeave={(e) => {
          if (!acceptDrop) return;
          e.stopPropagation();
          setDragOver(false);
        }}
        onDrop={(e) => {
          if (!onMove) return;
          const from = e.dataTransfer.getData(DRAG_TYPE);
          setDragOver(false);
          if (!from) return;
          e.preventDefault();
          e.stopPropagation();
          if (folderOf(from) === node.path) return; // no-op
          // Refuse moving a file under its own subtree (would orphan).
          if (node.path.startsWith(from.replace(/\.md$/i, "") + "/")) return;
          onMove(from, node.path);
        }}
        style={indent}
        className={clsx(
          "flex items-center gap-1 w-full text-left py-1 px-2 rounded-control transition-colors",
          dragOver
            ? "bg-accent-soft/40 text-accent ring-1 ring-accent/30"
            : "text-text-tertiary hover:bg-surface-subtle hover:text-text-primary",
        )}
      >
        <span className={clsx("inline-block transition-transform", open ? "rotate-90" : "")}>
          ▸
        </span>
        <span className="text-meta font-medium">{node.name}</span>
      </button>
      {open && (
        <TreeLevel
          nodes={sortChildren(node)}
          depth={depth + 1}
          current={current}
          onSelect={onSelect}
          stripExtension={stripExtension}
          badgeFor={badgeFor}
          onDelete={onDelete}
          onMove={onMove}
        />
      )}
    </li>
  );
}
