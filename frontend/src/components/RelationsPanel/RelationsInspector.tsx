import { lazy, Suspense } from "react";
import { Maximize2 } from "lucide-react";

import { t } from "../../lib/i18n";
import { graphHref } from "../../lib/graphHref";
import { usePersistedChoice } from "../../lib/usePersistedChoice";
import { SegmentedToggle } from "../SegmentedToggle";
import { AppLink } from "../ui/AppLink";
import { RelationsPanel } from "./RelationsPanel";

// The engine and the canvas loop load only once someone switches to the graph.
const MiniGraph = lazy(() => import("./MiniGraph").then((m) => ({ default: m.MiniGraph })));

type RelationsMode = "list" | "graph";
const MODES: readonly RelationsMode[] = ["list", "graph"];

interface Props {
  slug: string;
  assetId: string;
  canEdit: boolean;
}

/**
 * The reader inspector's relations tab: the same relations as a list (with
 * the editing actions) or as a graph of the direct neighbours, and the way
 * into the full graph view. The chosen mode is remembered.
 */
export function RelationsInspector({ slug, assetId, canEdit }: Props) {
  const [mode, setMode] = usePersistedChoice<RelationsMode>("ics-relations-mode", MODES, "list");
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <SegmentedToggle<RelationsMode>
          value={mode}
          onChange={setMode}
          ariaLabel={t("relations.mode")}
          options={[
            { value: "list", label: t("relations.modeList") },
            { value: "graph", label: t("relations.modeGraph") },
          ]}
        />
        <AppLink href={graphHref(slug)} className="inline-flex items-center gap-1.5 text-meta text-accent hover:underline">
          <Maximize2 size={13} aria-hidden />
          {t("relations.openGraph")}
        </AppLink>
      </div>
      {mode === "list" ? (
        <RelationsPanel slug={slug} assetId={assetId} canEdit={canEdit} />
      ) : (
        <Suspense fallback={<p className="text-meta text-text-tertiary">{t("common.loading")}</p>}>
          <MiniGraph slug={slug} />
        </Suspense>
      )}
    </div>
  );
}
