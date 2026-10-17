import { useCallback, useEffect, useMemo, useState } from "react";
import { Columns2, Rows3 } from "lucide-react";
import { api, DiffFileChange, DiffSummary, VersionRow } from "../api";
import { DiffFileBlock } from "../components/DiffFileBlock";
import { FileTree } from "../components/FileTree";
import { SegmentedToggle } from "../components/SegmentedToggle";
import { VersionPicker } from "../components/VersionPicker";
import { ReaderLayout } from "../components/reader/ReaderLayout";
import { ReaderToolbar } from "../components/reader/ReaderToolbar";
import { useInspector } from "../components/reader/useInspector";
import { PageContext } from "../components/shell/PageContext";
import { PanelSection } from "../components/ui/PanelSection";
import { formatApiError } from "../lib/apiError";
import { formatDateTime } from "../lib/format";
import { t, tn } from "../lib/i18n";
import { navigate } from "../lib/navigate";
import { usePersistedChoice } from "../lib/usePersistedChoice";

interface Props {
  slug: string;
  /** `?from=`/`?to=`; when absent, the two newest versions. */
  from?: number;
  to?: number;
}

type DiffResult = { key: string; summary?: DiffSummary; error?: string };
type DiffMode = "unified" | "split";
const DIFF_MODES = ["unified", "split"] as const;

/**
 * Full-screen version comparison (`/v/<slug>/diff?from=1&to=2`): a stack of
 * per-file diffs, with the changed-file tree in the inspector scrolling to a
 * file. A file's diff loads when its block nears the viewport, so requests
 * scale with visible files, not total files.
 */
export function VersionDiff({ slug, from, to }: Props) {
  const inspector = useInspector("collection");
  const [versions, setVersions] = useState<VersionRow[] | null>(null);
  const [assetId, setAssetId] = useState<string | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [docError, setDocError] = useState<string | null>(null);
  // The diff result and the selected file remember the version pair they
  // belong to, so switching pairs clears both without a reset effect.
  const [diff, setDiff] = useState<DiffResult | null>(null);
  const [picked, setPicked] = useState<{ key: string | null; path: string }>({
    key: null,
    path: "",
  });
  const [mode, onMode] = usePersistedChoice<DiffMode>("ics.diffMode", DIFF_MODES, "unified");

  // The doc provides the id and title (history is keyed by id, not slug) and
  // also checks access: the screen is linkable, so the user may not have come
  // from the list.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const doc = await api.getDoc(slug);
        if (cancelled) return;
        setAssetId(doc.id);
        setTitle(doc.title ?? doc.slug);
        const rows = await api.listVersions(doc.id);
        if (!cancelled) setVersions(rows);
      } catch (e) {
        if (!cancelled) setDocError(formatApiError(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug]);

  // Default to "what changed last": second newest to newest.
  const sorted = versions ? [...versions].sort((a, b) => a.version - b.version) : [];
  const latest = sorted[sorted.length - 1]?.version ?? 1;
  const previous = sorted[sorted.length - 2]?.version ?? latest;
  const fromV = from ?? previous;
  const toV = to ?? latest;
  const comparable = fromV !== toV;

  const diffKey = assetId && comparable ? `${assetId}:${fromV}:${toV}` : null;
  const currentDiff = diff && diff.key === diffKey ? diff : null;
  const summary = currentDiff?.summary ?? null;
  const error = docError ?? currentDiff?.error ?? null;
  const activePath = picked.key === diffKey ? picked.path : "";

  useEffect(() => {
    if (!assetId || diffKey === null) return;
    let cancelled = false;
    api.diffVersions(assetId, fromV, toV).then(
      (d) => {
        if (!cancelled) setDiff({ key: diffKey, summary: d });
      },
      (e) => {
        if (!cancelled) setDiff({ key: diffKey, error: formatApiError(e) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [assetId, fromV, toV, diffKey]);

  const loadFileDiff = useCallback(
    async (path: string) =>
      assetId ? (await api.diffVersionFile(assetId, fromV, toV, path)).diff : "",
    [assetId, fromV, toV],
  );

  const pick = useCallback(
    (next: { fromV: number; toV: number }) =>
      navigate(`/v/${slug}/diff?from=${next.fromV}&to=${next.toV}`),
    [slug],
  );

  // Stack order: modified, then added, then removed. Matches the sidebar
  // grouping and reads naturally as what happened to the document.
  const files = useMemo(() => orderFiles(summary?.files ?? []), [summary]);
  const changeByPath = useMemo(
    () => new Map(files.map((f) => [f.path, f.change] as const)),
    [files],
  );

  // A tree click scrolls to the block, which loads itself if it hasn't yet.
  const onSelect = useCallback(
    (path: string) => {
      setPicked({ key: diffKey, path });
      document
        .getElementById(anchorId(path))
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    [diffKey],
  );

  const versionBar = versions && versions.length >= 2 && (
    <div className="border-b border-border bg-surface px-(--gutter) py-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <VersionPicker versions={versions} fromV={fromV} toV={toV} onChange={pick} />
        {summary && (
          <p className="pb-2 text-meta text-text-secondary">
            <VersionCaption row={summary.from_meta} fallback={fromV} /> →{" "}
            <VersionCaption row={summary.to_meta} fallback={toV} />
          </p>
        )}
      </div>
    </div>
  );

  const withTree = Boolean(versions && versions.length >= 2);
  const closeIfDrawer = () => {
    if (!window.matchMedia("(min-width: 1280px)").matches) inspector.setOpen(false);
  };

  return (
    <>
      <PageContext
        crumbs={[
          { label: t("nav.documents"), href: "/" },
          { label: title ?? slug, href: `/v/${slug}` },
          { label: t("versionDiff.crumb") },
        ]}
      />
      <ReaderLayout
        banner={versionBar}
        toolbar={
          <ReaderToolbar
            start={
              <>
                <DiffModeToggle mode={mode} onChange={onMode} />
                {summary && <span className="max-sm:hidden">{tn("format.fileCount", files.length)}</span>}
              </>
            }
            menu={[]}
            menuLabel={t("versionDiff.crumb")}
            inspector={
              withTree
                ? {
                    open: inspector.open,
                    toggle: () => inspector.setOpen(!inspector.open),
                    label: t(inspector.open ? "reader.inspectorHide" : "reader.inspectorShow"),
                  }
                : undefined
            }
          />
        }
        inspector={inspector}
        panels={
          withTree
            ? {
                files: (
                  <PanelSection title={t("versionDiff.changes", { count: files.length })} last>
                    <FileTree
                      paths={files.map((f) => f.path)}
                      current={activePath}
                      stripExtension={false}
                      badgeFor={(p) => <ChangeBadge change={changeByPath.get(p)} />}
                      onSelect={(p) => {
                        onSelect(p);
                        closeIfDrawer();
                      }}
                    />
                  </PanelSection>
                ),
              }
            : {}
        }
      >
        <div className="max-w-full space-y-6 px-(--gutter) py-6">
          {error && <p className="text-ui text-danger">{error}</p>}
          {versions && versions.length < 2 && !error && <p className="text-text-secondary">{t("versionDiff.singleVersion")}</p>}
          {!summary && !error && comparable && <p className="text-meta text-text-secondary">{t("versionDiff.computing")}</p>}
          {summary && files.length === 0 && <p className="text-meta text-text-secondary">{t("versionDiff.noChanges")}</p>}
          {files.map((f) => (
            <DiffFileBlock key={f.path} file={f} mode={mode} load={loadFileDiff} active={activePath === f.path} anchorId={anchorId(f.path)} />
          ))}
        </div>
      </ReaderLayout>
    </>
  );
}

const CHANGE_ORDER: Record<DiffFileChange["change"], number> = {
  modified: 0,
  added: 1,
  removed: 2,
};

function orderFiles(files: DiffFileChange[]): DiffFileChange[] {
  return [...files].sort(
    (a, b) => CHANGE_ORDER[a.change] - CHANGE_ORDER[b.change] || a.path.localeCompare(b.path),
  );
}

/** Anchor for a file block; paths contain slashes and dots, hence the encoding. */
function anchorId(path: string): string {
  return `diff-${encodeURIComponent(path)}`;
}

function DiffModeToggle({
  mode,
  onChange,
}: {
  mode: DiffMode;
  onChange: (m: DiffMode) => void;
}) {
  return (
    <SegmentedToggle
      value={mode}
      onChange={onChange}
      ariaLabel={t("versionDiff.modeLabel")}
      options={[
        { value: "unified", label: t("versionDiff.unified"), icon: <Rows3 size={13} aria-hidden /> },
        { value: "split", label: t("versionDiff.split"), icon: <Columns2 size={13} aria-hidden /> },
      ]}
    />
  );
}

function ChangeBadge({ change }: { change?: DiffFileChange["change"] }) {
  if (!change) return null;
  const [sign, cls] =
    change === "added"
      ? ["+", "text-success"]
      : change === "removed"
        ? ["−", "text-danger"]
        : ["~", "text-warning"];
  return <span className={cls}>{sign}</span>;
}

/** "v1 · <date>, 13:58 · Jane Doe": who made the version and when. */
function VersionCaption({ row, fallback }: { row: VersionRow | null; fallback: number }) {
  if (!row) return <span className="font-code">v{fallback}</span>;
  const when = formatDateTime(row.created_at);
  return (
    <span>
      <span className="font-code text-text-secondary">v{row.version}</span>
      {when && ` · ${when}`}
      {row.author && ` · ${row.author}`}
    </span>
  );
}
