import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { SlidersHorizontal } from "lucide-react";
import type { Me } from "../../api";
import { t } from "../../lib/i18n";
import { BrandMark } from "../BrandMark";
import { AppLink } from "../ui/AppLink";
import { Drawer } from "../ui/Drawer";
import { iconButtonClass } from "../ui/IconButton";
import { Popover } from "../ui/Popover";
import { overlayOpen } from "../ui/useOverlay";
import { AppSidebar } from "./AppSidebar";
import { AppTopbar } from "./AppTopbar";
import { CommandPalette } from "./CommandPalette";
import { Preferences } from "./Preferences";
import { ShellContext, type ShellApi } from "./shellContext";
import { useSidebarLayout } from "./useSidebarLayout";

interface Props {
  /** Signed-in user; `null` renders the public frame (link visitors). */
  me: Me | null;
  children: ReactNode;
}

/**
 * The frame of every page (DESIGN.md 2), mounted once by the router so the
 * sidebar keeps its scroll and folded groups. Children stay at the same tree
 * position, so a late sign-in adds the chrome without remounting the page.
 */
export function AppShell({ me, children }: Props) {
  const [focusMode, setFocusMode] = useState(false);
  const [contextSlot, setContextSlot] = useState<HTMLElement | null>(null);
  const [activeHref, setActiveHref] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const layout = useSidebarLayout(focusMode);
  const { mode, drawerOpen, closeDrawer, openDrawer } = layout;
  const closePalette = useCallback(() => setPaletteOpen(false), []);

  // Escape leaves focus mode wherever a page turned it on, after any open overlay took its own Escape.
  useEffect(() => {
    if (!focusMode) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented && !overlayOpen()) setFocusMode(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [focusMode]);

  useEffect(() => {
    if (!me) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [me]);

  const api: ShellApi = useMemo(
    () => ({ contextSlot, focusMode, setFocusMode, setActiveHref, signedIn: me !== null }),
    [contextSlot, focusMode, me],
  );

  const column = me && mode !== "hidden";

  return (
    <ShellContext.Provider value={api}>
      <a
        href="#main"
        className="sr-only z-[80] rounded-control bg-surface px-3 py-2 text-ui font-medium text-accent shadow-floating focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        {t("shell.skipToContent")}
      </a>
      <div className="flex min-h-dvh bg-canvas">
        {column ? (
          <aside
            className={clsx(
              "sticky top-0 h-dvh shrink-0 border-r border-border bg-surface",
              mode === "expanded" ? "w-(--sidebar-width)" : "w-(--sidebar-rail)",
            )}
          >
            <AppSidebar
              me={me}
              variant={mode === "expanded" ? "expanded" : "rail"}
              // Tablets keep the rail and open the full tree over the page instead.
              onToggleCollapsed={layout.desktop ? layout.toggleCollapsed : openDrawer}
              activeHref={activeHref}
            />
          </aside>
        ) : null}
        <div className="flex min-w-0 flex-1 flex-col">
          {me ? (
            <AppTopbar
              me={me}
              showBrand={mode === "hidden"}
              onOpenNav={mode === "hidden" ? openDrawer : undefined}
              onOpenSearch={() => setPaletteOpen(true)}
            />
          ) : (
            <PublicTopbar />
          )}
          <div ref={setContextSlot} />
          <main id="main" tabIndex={-1} className="flex min-h-0 flex-1 flex-col outline-none">
            {children}
          </main>
        </div>
      </div>
      {me && (
        <Drawer
          id="app-nav-drawer"
          open={drawerOpen && mode !== "expanded"}
          onClose={closeDrawer}
          title={t("nav.label")}
          header={
            <AppLink href="/" onClick={closeDrawer} aria-label={t("chrome.home")} className="inline-flex rounded-control p-1 -m-1 text-text-primary">
              <BrandMark size={22} />
            </AppLink>
          }
        >
          <AppSidebar me={me} variant="drawer" onNavigate={closeDrawer} activeHref={activeHref} />
        </Drawer>
      )}
      {me && <CommandPalette me={me} open={paletteOpen} onClose={closePalette} />}
    </ShellContext.Provider>
  );
}

/** Bar of pages for people without a session: the brand and how the page looks. */
function PublicTopbar() {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/85">
      <div className="flex h-14 items-center justify-between gap-3 px-(--gutter)">
        <a href="/" aria-label={t("chrome.home")} className="rounded-control p-1 -m-1 text-text-primary">
          <BrandMark size={22} />
        </a>
        <Popover
          label={t("shell.viewSettings")}
          align="end"
          widthClass="w-80"
          trigger={(props) => (
            <button type="button" {...props} aria-label={t("shell.viewSettings")} title={t("shell.viewSettings")} className={iconButtonClass("ghost")}>
              <SlidersHorizontal size={18} aria-hidden />
            </button>
          )}
        >
          {() => <Preferences saveLocale={false} />}
        </Popover>
      </div>
    </header>
  );
}
