import { Suspense, lazy, type ComponentProps, type ReactNode } from "react";
import { FileText, Network } from "lucide-react";
import { t } from "../lib/i18n";
import { MarkdownView } from "./MarkdownView";
import { SegmentedToggle } from "./SegmentedToggle";
import type { VaultGraphProps } from "./VaultGraph";

// Lazy so md_single documents and text-mode collections never load the graph code.
const VaultGraph = lazy(() =>
  import("./VaultGraph").then((m) => ({ default: m.VaultGraph })),
);

export type VaultMode = "text" | "graph";

export function VaultModeToggle({
  mode,
  onChange,
}: {
  mode: VaultMode;
  onChange: (m: VaultMode) => void;
}) {
  return (
    <SegmentedToggle
      value={mode}
      onChange={onChange}
      ariaLabel={t("vaultMode.label")}
      options={[
        { value: "text", label: t("vaultMode.text"), icon: <FileText size={13} aria-hidden /> },
        { value: "graph", label: t("vaultMode.graph"), icon: <Network size={13} aria-hidden /> },
      ]}
    />
  );
}

/** Reader body shared by the owner viewer and the share view: either the
 * vault graph or the rendered Markdown followed by `children` (the version
 * history). */
export function VaultReaderBody({
  graph,
  activePath,
  onOpenFile,
  onModeChange,
  markdown,
  downloadHref,
  children,
}: {
  /** Graph data source while the graph mode is active, otherwise null. */
  graph: Pick<VaultGraphProps, "source" | "fetcher"> | null;
  activePath: string;
  onOpenFile: (path: string) => void;
  onModeChange: (mode: VaultMode) => void;
  markdown: Omit<ComponentProps<typeof MarkdownView>, "downloadHref">;
  downloadHref: string | undefined;
  children: ReactNode;
}) {
  if (graph) {
    return (
      <div className="px-(--gutter) py-4">
        <Suspense fallback={<div className="text-text-tertiary">{t("vaultGraph.loading")}</div>}>
          <VaultGraph
            {...graph}
            currentPath={activePath}
            onOpenFile={(p) => {
              onOpenFile(p);
              onModeChange("text");
            }}
          />
        </Suspense>
      </div>
    );
  }
  return (
    <>
      <MarkdownView {...markdown} downloadHref={downloadHref} />
      {/* History sits inside the reader, not below the whole layout: for a
          collection the layout is pinned to the viewport height, so a section
          appended below would add a second document scroll and push the
          "outdated version" banner off screen. */}
      {children}
    </>
  );
}
