import { useEffect, useId, useRef, type ReactNode } from "react";
import { clsx } from "clsx";
import { t, type MessageKey } from "../../lib/i18n";
import { playEnter } from "../../lib/motion";
import { useShell } from "../shell/shellContext";
import { Drawer } from "../ui/Drawer";
import { InspectorResizeHandle } from "./InspectorResizeHandle";
import { useInspectorWidth } from "./useInspectorWidth";

export type InspectorTab = "files" | "outline" | "details" | "relations" | "history";

const INSPECTOR_LABEL: Record<InspectorTab, MessageKey> = {
  files: "reader.tabFiles",
  outline: "reader.tabOutline",
  details: "reader.tabDetails",
  relations: "reader.tabRelations",
  history: "reader.tabHistory",
};

export interface InspectorState {
  open: boolean;
  tab: InspectorTab;
  /** Beside the text (wide screens) rather than a drawer over it. */
  docked: boolean;
  setOpen: (open: boolean) => void;
  setTab: (tab: InspectorTab) => void;
}

interface Props {
  /** Outdated-version and superseded bars, above the toolbar. */
  banner?: ReactNode;
  toolbar: ReactNode;
  inspector: InspectorState;
  /** Tabs the inspector offers for this document and role, in order. */
  panels: Partial<Record<InspectorTab, ReactNode>>;
  children: ReactNode;
}


/**
 * The reader: the document takes the page, its tools sit in one bar above
 * it, and the inspector (files, contents, details, relations, history) is one panel
 * beside the text on wide screens and a drawer elsewhere. The inspector is
 * the document's toolbox, never a second navigation.
 */
export function ReaderLayout({ banner, toolbar, inspector, panels, children }: Props) {
  const { docked } = inspector;
  const { focusMode } = useShell();
  const tabs = (Object.keys(INSPECTOR_LABEL) as InspectorTab[]).filter((k) => panels[k] !== undefined);
  const tab = tabs.includes(inspector.tab) ? inspector.tab : (tabs[0] ?? "outline");
  const body = <InspectorBody tabs={tabs} tab={tab} onTab={inspector.setTab} panels={panels} />;
  const asideRef = useRef<HTMLElement>(null);
  const showDocked = docked && inspector.open && tabs.length > 0 && !focusMode;
  const inspectorWidth = useInspectorWidth();

  useEffect(() => {
    if (showDocked) playEnter(asideRef.current, "drawer-right");
  }, [showDocked]);

  return (
    <div className="flex min-h-0 flex-1">
      <div className="min-w-0 flex-1 bg-surface">
        {banner}
        {toolbar}
        {children}
      </div>
      {showDocked && (
        <aside
          ref={asideRef}
          id="reader-inspector"
          aria-label={t("reader.inspector")}
          style={{ width: inspectorWidth.width }}
          className="sticky top-14 h-[calc(100dvh-var(--topbar-height))] shrink-0 border-l border-border bg-surface"
        >
          <InspectorResizeHandle {...inspectorWidth} />
          <div className="h-full overflow-y-auto overscroll-contain">{body}</div>
        </aside>
      )}
      {!docked && (
        <Drawer
          id="reader-inspector"
          side="right"
          open={inspector.open && tabs.length > 0}
          onClose={() => inspector.setOpen(false)}
          title={t("reader.inspector")}
          widthClass="w-[min(22rem,90vw)]"
        >
          {body}
        </Drawer>
      )}
    </div>
  );
}

function InspectorBody({
  tabs,
  tab,
  onTab,
  panels,
}: {
  tabs: InspectorTab[];
  tab: InspectorTab;
  onTab: (t: InspectorTab) => void;
  panels: Partial<Record<InspectorTab, ReactNode>>;
}) {
  const id = useId();
  return (
    <div className="flex min-h-full flex-col">
      {tabs.length > 1 && (
        <div
          role="tablist"
          aria-label={t("reader.inspector")}
          className="sticky top-0 z-10 flex gap-0.5 overflow-x-auto border-b border-border bg-surface px-1 pt-2 [scrollbar-width:none]"
          onKeyDown={(e) => {
            if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
            const at = tabs.indexOf(tab);
            const next = tabs[(at + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
            if (!next) return;
            onTab(next);
            document.getElementById(`${id}-${next}`)?.focus();
          }}
        >
          {tabs.map((k) => (
            <button
              key={k}
              id={`${id}-${k}`}
              type="button"
              role="tab"
              aria-selected={k === tab}
              aria-controls={`${id}-${k}-panel`}
              tabIndex={k === tab ? 0 : -1}
              onClick={() => onTab(k)}
              className={clsx(
                "relative -mb-px h-9 shrink-0 whitespace-nowrap px-1 text-ui transition-colors duration-150",
                k === tab
                  ? "font-medium text-text-primary after:absolute after:inset-x-1 after:bottom-0 after:h-0.5 after:rounded-full after:bg-accent"
                  : "text-text-secondary hover:text-text-primary",
              )}
            >
              {t(INSPECTOR_LABEL[k])}
            </button>
          ))}
        </div>
      )}
      <div
        role={tabs.length > 1 ? "tabpanel" : undefined}
        id={`${id}-${tab}-panel`}
        aria-labelledby={tabs.length > 1 ? `${id}-${tab}` : undefined}
        className="flex-1 px-4 py-4"
      >
        {panels[tab]}
      </div>
    </div>
  );
}
