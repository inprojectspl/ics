import type { ReactNode } from "react";
import { Minimize2, PanelRightOpen } from "lucide-react";

import { IconButton } from "../../components/ui/IconButton";
import { t } from "../../lib/i18n";

/** Screen width the open panel covers: its 22rem and its margin from the canvas edge. */
export const PANEL_INSET = 352 + 12;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Title of the selected card, shown on the minimised pill. */
  selected: string | null;
  children: ReactNode;
}

/**
 * The explorer's details and list as a window floating over the canvas,
 * so the graph keeps the whole width; minimised it is a small pill in the
 * corner that names the selected card. It takes the canvas height; the
 * canvas moves its minimap beside it.
 */
export function FloatingPanel({ open, onOpenChange, selected, children }: Props) {
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        aria-expanded={false}
        aria-controls="graph-explorer-panel"
        className="absolute right-3 top-3 z-10 inline-flex max-w-[min(20rem,calc(100%-1.5rem))] items-center gap-2 rounded-full border border-border bg-surface/95 px-3.5 py-2 text-ui text-text-primary shadow-floating backdrop-blur-sm hover:bg-surface-hover"
      >
        <PanelRightOpen size={15} aria-hidden className="shrink-0 text-text-secondary" />
        <span className="truncate">{selected ?? t("graphExplorer.panelButton")}</span>
      </button>
    );
  }
  return (
    <section
      id="graph-explorer-panel"
      aria-label={t("graphExplorer.panelButton")}
      className="absolute inset-y-3 right-3 z-10 flex w-[22rem] max-w-[calc(100%-1.5rem)] flex-col overflow-hidden rounded-card border border-border bg-surface shadow-floating"
    >
      {/* Positioned by a wrapper: the button sits inside its tooltip anchor. */}
      <div className="absolute right-1.5 top-1.5 z-10">
        <IconButton
          size="sm"
          label={t("graphExplorer.panelMinimize")}
          aria-expanded
          aria-controls="graph-explorer-panel"
          icon={<Minimize2 size={15} aria-hidden />}
          onClick={() => onOpenChange(false)}
        />
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  );
}
