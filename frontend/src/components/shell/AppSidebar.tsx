import { useCallback, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { PanelLeftClose, PanelLeftOpen, Settings } from "lucide-react";
import { api, type Me, type ProjectSummary } from "../../api";
import { formatBytes } from "../../lib/format";
import { nameCollator, t } from "../../lib/i18n";
import { playEnter } from "../../lib/motion";
import { qk, projectListQuery } from "../../lib/queries";
import { useRecentProjects } from "../../lib/recentProjects";
import { useLocation } from "../../lib/useLocation";
import { AppLink } from "../ui/AppLink";
import { BrandMark } from "../BrandMark";
import { BuiltBy } from "../BuiltBy";
import { IconButton } from "../ui/IconButton";
import { navTree, sectionOf, type NavGroup, type ProjectLink } from "./navModel";
import { RailButton, RailCredit, RailLink, SidebarGroup, SidebarRailGroup } from "./SidebarGroup";

/** How many projects the tree lists; the rest is one click away in "All projects". */
const PROJECT_LIMIT = 5;
const NO_PROJECTS: ProjectSummary[] = [];

interface Props {
  me: Me;
  variant: "expanded" | "rail" | "drawer";
  /** Collapse or expand the persistent column (desktop). */
  onToggleCollapsed?: () => void;
  /** Close the drawer after a route was picked. */
  onNavigate?: () => void;
  /** Sidebar entry the page asked to mark (`ShellApi.setActiveHref`). */
  activeHref: string | null;
}

function useNavTree(me: Me): NavGroup[] {
  const projects = useQuery({
    ...projectListQuery,
  }).data ?? NO_PROJECTS;
  const recent = useRecentProjects();
  return useMemo(() => {
    const byName = nameCollator();
    const bySlug = new Map(projects.map((p) => [p.slug, p]));
    const picked: ProjectLink[] = [];
    for (const slug of recent.slice(0, PROJECT_LIMIT)) {
      const p = bySlug.get(slug);
      if (p) picked.push(p);
    }
    // Until the user has opened a few, fill up with the rest by name.
    for (const p of [...projects].sort((a, b) => byName.compare(a.name, b.name))) {
      if (picked.length >= PROJECT_LIMIT) break;
      if (!picked.includes(p)) picked.push(p);
    }
    // Recency picks which projects are listed, the name orders them: opening
    // one must not make the list jump under the pointer.
    return navTree(me, picked.sort((a, b) => byName.compare(a.name, b.name)));
  }, [me, projects, recent]);
}

/**
 * The one navigation of the signed-in app: modules, their views and the
 * recent projects. The column scrolls on its own; the footer (settings,
 * storage) stays put.
 */
export function AppSidebar({ me, variant, onToggleCollapsed, onNavigate, activeHref }: Props) {
  const groups = useNavTree(me);
  const loc = useLocation();
  const treeRef = useRef<HTMLDivElement>(null);
  const [folded, toggleGroup] = useFoldedGroups();

  const activeLeaf = useMemo(() => {
    for (const g of groups) {
      for (const leaf of g.children) {
        if (activeHref ? leaf.href === activeHref : leaf.match(loc)) return leaf.id;
      }
    }
    return null;
  }, [groups, loc, activeHref]);
  const section = sectionOf(activeHref ?? loc.pathname);
  const groupActive = (g: NavGroup) =>
    g.id === section || g.children.some((c) => c.id === activeLeaf);

  const rail = variant === "rail";
  const toggle = () => {
    onToggleCollapsed?.();
    // The labels fade back in; the width itself switches at once.
    requestAnimationFrame(() => playEnter(treeRef.current, "fade"));
  };
  const collapseToggle = onToggleCollapsed && (
    <IconButton
      label={t("shell.collapseSidebar")}
      icon={<PanelLeftClose size={18} aria-hidden />}
      onClick={toggle}
    />
  );  const settingsLabel = t("account.menu");
  const settingsActive = loc.pathname.startsWith("/account");

  return (
    <nav aria-label={t("nav.label")} className="flex h-full min-h-0 flex-col">
      {variant !== "drawer" && (
        <div className={clsx("flex h-14 shrink-0 items-center", rail ? "justify-center" : "justify-between pl-4 pr-2")}>
          <AppLink href="/" aria-label={t("chrome.home")} className="-m-1 rounded-control p-1 text-text-primary">
            <BrandMark size={22} withWord={!rail} />
          </AppLink>
          {onToggleCollapsed && !rail && collapseToggle}
        </div>
      )}

      <div ref={treeRef} className={clsx("min-h-0 flex-1 overflow-y-auto overscroll-contain", rail ? "px-2.5 py-2" : "px-2 py-2")}>
        {rail && onToggleCollapsed && (
          <div className="mb-2 border-b border-border pb-2">
            <RailButton label={t("shell.expandSidebar")} icon={<PanelLeftOpen size={20} aria-hidden />} onClick={toggle} />
          </div>
        )}
        <ul className="space-y-1">
          {groups.map((g) =>
            rail ? (
              <SidebarRailGroup key={g.id} group={g} active={groupActive(g)} activeLeaf={activeLeaf} />
            ) : (
              <SidebarGroup
                key={g.id}
                group={g}
                active={groupActive(g)}
                activeLeaf={activeLeaf}
                expanded={!folded.has(g.id)}
                onToggle={() => toggleGroup(g.id)}
                onNavigate={onNavigate}
              />
            ),
          )}
        </ul>
      </div>

      <div className={clsx("shrink-0 border-t border-border", rail ? "px-2.5 py-2" : "p-2")}>
        {rail ? (
          <div className="space-y-1">
            <RailLink href="/account/notifications" label={settingsLabel} icon={<Settings size={20} aria-hidden />} active={settingsActive} />
            <RailCredit />
          </div>
        ) : (
          <>
            <AppLink
              href="/account/notifications"
              onClick={onNavigate}
              aria-current={settingsActive ? "page" : undefined}
              className={clsx(
                "flex min-h-9 items-center gap-2.5 rounded-control px-2 py-1.5 text-ui font-medium transition-colors duration-150",
                settingsActive ? "bg-accent-soft text-text-primary" : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
              )}
            >
              <Settings size={18} aria-hidden className={settingsActive ? "text-accent" : undefined} />
              {settingsLabel}
            </AppLink>
            <StorageMeter />
            <BuiltBy variant="sidebar" />
          </>
        )}
      </div>
    </nav>
  );
}

/** Ids of the groups the user folded, remembered across pages and reloads. */
function useFoldedGroups(): [ReadonlySet<string>, (id: string) => void] {
  const [folded, setFolded] = useState<ReadonlySet<string>>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(FOLDED_KEY) ?? "[]");
      return new Set(Array.isArray(raw) ? raw.filter((v): v is string => typeof v === "string") : []);
    } catch {
      return new Set();
    }
  });
  const toggle = useCallback((id: string) => {
    setFolded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      try {
        localStorage.setItem(FOLDED_KEY, JSON.stringify([...next]));
      } catch {
        /* the choice just won't survive a reload */
      }
      return next;
    });
  }, []);
  return [folded, toggle];
}

const FOLDED_KEY = "ics-nav-folded";

/** Storage used out of the quota, quiet until it gets tight. */
function StorageMeter() {
  const quota = useQuery({ queryKey: qk.quota(), queryFn: api.myQuota }).data;
  if (!quota || quota.quota_bytes <= 0) return null;
  const pct = Math.min(100, (quota.used_bytes / quota.quota_bytes) * 100);
  const tone = pct >= 95 ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-accent";
  return (
    <div className="px-2 pb-1 pt-2.5">
      <div className="flex items-baseline justify-between gap-2 text-meta text-text-secondary">
        <span>{t("quota.title")}</span>
        <span className="tabular-nums">{Math.round(pct)}%</span>
      </div>
      <div
        className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-subtle"
        role="progressbar"
        aria-label={t("quota.usage")}
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className={clsx("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-caption tabular-nums text-text-secondary">
        {formatBytes(quota.used_bytes)} / {formatBytes(quota.quota_bytes)}
      </p>
    </div>
  );
}
