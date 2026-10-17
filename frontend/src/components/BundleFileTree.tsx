import { useMemo } from "react";
import { clsx } from "clsx";
import { t, tn, type PluralKey } from "../lib/i18n";

interface Props {
  files: string[];
  entryPath?: string | null;
}

type Category = "html" | "style" | "script" | "image" | "font" | "media" | "data" | "other";

interface TreeNode {
  name: string;
  full: string;
  children: Map<string, TreeNode>;
  isFile: boolean;
}

const CATEGORY_LABELS: Record<Category, { label: string; plural: PluralKey }> = {
  html: { label: "HTML", plural: "bundleFileTree.catHtml" },
  style: { label: "CSS", plural: "bundleFileTree.catStyle" },
  script: { label: "JS", plural: "bundleFileTree.catScript" },
  image: { label: "IMG", plural: "bundleFileTree.catImage" },
  font: { label: "FONT", plural: "bundleFileTree.catFont" },
  media: { label: "MEDIA", plural: "bundleFileTree.catMedia" },
  data: { label: "DATA", plural: "bundleFileTree.catData" },
  other: { label: "OTHER", plural: "bundleFileTree.catOther" },
};

function categoryOf(path: string): Category {
  const ext = path.toLowerCase().split(".").pop() || "";
  if (ext === "html" || ext === "htm") return "html";
  if (ext === "css") return "style";
  if (ext === "js" || ext === "mjs" || ext === "map") return "script";
  if (["png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "avif"].includes(ext)) return "image";
  if (["woff", "woff2", "ttf", "otf", "eot"].includes(ext)) return "font";
  if (["mp4", "webm", "ogg", "mp3", "wav"].includes(ext)) return "media";
  if (["json", "txt", "md", "csv"].includes(ext)) return "data";
  return "other";
}

function buildTree(files: string[]): TreeNode {
  const root: TreeNode = { name: "", full: "", children: new Map(), isFile: false };
  for (const f of files) {
    const parts = f.split("/");
    let cur = root;
    parts.forEach((part, i) => {
      const isLast = i === parts.length - 1;
      let child = cur.children.get(part);
      if (!child) {
        child = {
          name: part,
          full: parts.slice(0, i + 1).join("/"),
          children: new Map(),
          isFile: isLast,
        };
        cur.children.set(part, child);
      }
      cur = child;
    });
  }
  return root;
}

function sortChildren(node: TreeNode): [string, TreeNode][] {
  return Array.from(node.children.entries()).sort(([, a], [, b]) => {
    if (a.isFile !== b.isFile) return a.isFile ? 1 : -1;
    return a.name.localeCompare(b.name);
  });
}

/**
 * Visual tree of a html_bundle's contents. Owner-only - share visitors
 * see only the landing card. Defaults to collapsed because a 50-file
 * bundle would dominate the viewport; expanding reveals a directory
 * tree where folders use native <details> for keyboard a11y.
 */
export function BundleFileTree({ files, entryPath }: Props) {
  const { tree, summary, total } = useMemo(() => {
    const built = buildTree(files);
    const counts: Record<Category, number> = {
      html: 0, style: 0, script: 0, image: 0, font: 0, media: 0, data: 0, other: 0,
    };
    for (const f of files) counts[categoryOf(f)]++;
    const summary = (Object.keys(counts) as Category[])
      .filter((c) => counts[c] > 0)
      .sort((a, b) => counts[b] - counts[a]);
    return { tree: built, summary, total: files.length };
  }, [files]);

  if (total === 0) return null;

  return (
    <details className="group rounded-control border border-border bg-surface/60 mb-8">
      <summary
        className={clsx(
          "cursor-pointer list-none px-5 py-3.5 flex items-baseline gap-3",
          "[&::-webkit-details-marker]:hidden",
          "group-open:border-b group-open:border-border",
        )}
      >
        <span className="text-meta text-text-secondary shrink-0 font-medium">
          {t("bundleFileTree.title")}
        </span>
        <span className="font-code tabular-nums text-meta text-text-primary shrink-0">
          {tn("format.fileCount", total)}
        </span>
        <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-meta text-text-tertiary min-w-0">
          {summary.map((cat) => (
            <span key={cat}>
              <span className="font-code tabular-nums text-text-secondary">
                {/* count rebuilt; cheap for <= a few hundred files */}
                {files.filter((f) => categoryOf(f) === cat).length}
              </span>{" "}
              {tn(CATEGORY_LABELS[cat].plural, files.filter((f) => categoryOf(f) === cat).length)}
            </span>
          ))}
        </span>
        <span
          aria-hidden
          className="ml-auto font-code text-meta text-text-tertiary shrink-0 transition-transform group-open:rotate-90"
        >
          ›
        </span>
      </summary>
      <div className="px-5 py-4">
        <ul className="space-y-0.5">
          <TreeChildren node={tree} depth={0} entryPath={entryPath ?? null} />
        </ul>
      </div>
    </details>
  );
}

function TreeChildren({
  node,
  depth,
  entryPath,
}: {
  node: TreeNode;
  depth: number;
  entryPath: string | null;
}) {
  const entries = sortChildren(node);
  return (
    <>
      {entries.map(([, child]) => (
        <TreeRow key={child.full} node={child} depth={depth} entryPath={entryPath} />
      ))}
    </>
  );
}

function TreeRow({
  node,
  depth,
  entryPath,
}: {
  node: TreeNode;
  depth: number;
  entryPath: string | null;
}) {
  const indent = { paddingLeft: `${depth * 14}px` };
  if (node.isFile) {
    const cat = categoryOf(node.name);
    const isEntry = node.full === entryPath;
    return (
      <li
        className="flex items-baseline gap-2.5 py-0.5"
        style={indent}
      >
        <span
          aria-hidden
          className="font-code text-meta text-text-tertiary select-none"
        >
          ·
        </span>
        <code
          className={clsx(
            "font-code text-ui truncate",
            isEntry ? "text-accent font-medium" : "text-text-secondary",
          )}
        >
          {node.name}
        </code>
        {isEntry && (
          <span className="text-meta text-accent shrink-0 font-medium">
            {t("bundleFileTree.entry")}
          </span>
        )}
        <span
          className={clsx(
            "text-meta shrink-0 ml-auto font-medium",
            "text-text-tertiary",
          )}
        >
          {CATEGORY_LABELS[cat].label}
        </span>
      </li>
    );
  }
  const defaultOpen = depth < 2;
  return (
    <li>
      <details open={defaultOpen}>
        <summary
          className={clsx(
            "list-none cursor-pointer flex items-baseline gap-2.5 py-0.5",
            "hover:text-text-primary",
            "[&::-webkit-details-marker]:hidden",
          )}
          style={indent}
        >
          <span
            aria-hidden
            className="font-code text-meta text-text-tertiary select-none transition-transform inline-block w-3"
          >
            ▸
          </span>
          <code className="font-code text-ui text-text-primary">{node.name}/</code>
          <span className="font-code tabular-nums text-meta text-text-tertiary shrink-0 ml-auto">
            {countFiles(node)}
          </span>
        </summary>
        <ul className="space-y-0.5">
          <TreeChildren node={node} depth={depth + 1} entryPath={entryPath} />
        </ul>
      </details>
    </li>
  );
}

function countFiles(node: TreeNode): number {
  let n = 0;
  for (const child of node.children.values()) {
    n += child.isFile ? 1 : countFiles(child);
  }
  return n;
}
