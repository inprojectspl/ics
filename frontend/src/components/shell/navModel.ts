import {
  FileText,
  FolderKanban,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import type { Me } from "../../api";
import type { MessageKey } from "../../lib/i18n";
import { scopeHref, type AssetScope } from "../../lib/useAssetFilter";

/** Top-level area of the app; decides the active sidebar group. */
export type NavSection = "documents" | "projects" | "admin" | "account" | "notifications";

export interface NavLeaf {
  id: string;
  href: string;
  label: MessageKey | { text: string };
  /** Decides whether the current location is this entry. */
  match: (loc: { pathname: string; search: URLSearchParams }) => boolean;
}

export interface NavGroup {
  id: Exclude<NavSection, "account" | "notifications">;
  href: string;
  label: MessageKey;
  icon: LucideIcon;
  children: NavLeaf[];
}

function scopeOf(search: URLSearchParams): AssetScope {
  const scopes: AssetScope[] = ["state:pinned", "state:mine", "state:shared-with-me", "admin:review"];
  return scopes.find((s) => search.getAll("f").includes(s)) ?? "all";
}

const docLeaf = (scope: AssetScope, label: MessageKey): NavLeaf => ({
  id: `documents:${scope}`,
  href: scopeHref(scope),
  label,
  match: ({ pathname, search }) => pathname === "/" && scopeOf(search) === scope,
});

const pathLeaf = (id: string, href: string, label: MessageKey): NavLeaf => ({
  id,
  href,
  label,
  match: ({ pathname }) => pathname === href,
});

const DOCUMENT_SCOPES: ReadonlyArray<{ scope: AssetScope; label: MessageKey }> = [
  { scope: "all", label: "sidebarNav.all" },
  { scope: "state:mine", label: "sidebarNav.mine" },
  { scope: "state:shared-with-me", label: "sidebarNav.sharedWithMe" },
  { scope: "state:pinned", label: "sidebarNav.pinned" },
];

/** Administration screens in sidebar order; each lives at `/admin/<tab>`. */
export const ADMIN_SCREENS = [
  { tab: "users", label: "nav.adminUsers" },
  { tab: "review", label: "nav.adminReview" },
  { tab: "cdn", label: "nav.adminCdn" },
  { tab: "doc-types", label: "nav.adminDocTypes" },
  { tab: "audit", label: "nav.adminAudit" },
] as const satisfies readonly { tab: string; label: MessageKey }[];

export type AdminTab = (typeof ADMIN_SCREENS)[number]["tab"];

const ADMIN_LEAVES: NavLeaf[] = ADMIN_SCREENS.map((s) => pathLeaf(`admin:${s.tab}`, `/admin/${s.tab}`, s.label));

export interface ProjectLink {
  slug: string;
  name: string;
}

/**
 * The navigation tree for this user: documents, projects (recent ones in the
 * given order, then "all") and administration for admins. Only hides what
 * the backend would refuse anyway.
 */
export function navTree(me: Me, projects: readonly ProjectLink[]): NavGroup[] {
  const groups: NavGroup[] = [
    {
      id: "documents",
      href: "/",
      label: "nav.documents",
      icon: FileText,
      children: [
        ...DOCUMENT_SCOPES.map(({ scope, label }) => docLeaf(scope, label)),
        pathLeaf("documents:graph", "/graph", "sidebarNav.graph"),
      ],
    },
    {
      id: "projects",
      href: "/projects",
      label: "nav.projects",
      icon: FolderKanban,
      children: [
        ...projects.map((p) => ({
          id: `project:${p.slug}`,
          href: `/projects/${p.slug}`,
          label: { text: p.name },
          match: ({ pathname }: { pathname: string }) =>
            pathname === `/projects/${p.slug}` || pathname.startsWith(`/projects/${p.slug}/`),
        })),
        pathLeaf("projects:all", "/projects", "nav.allProjects"),
      ],
    },
  ];
  if (me.role === "admin") {
    groups.push({
      id: "admin",
      href: "/admin/users",
      label: "nav.admin",
      icon: ShieldCheck,
      children: ADMIN_LEAVES,
    });
  }
  return groups;
}

/** Section of a path, for the active group when no leaf matches exactly. */
export function sectionOf(pathname: string): NavSection | null {
  if (pathname === "/" || pathname.startsWith("/v/") || pathname === "/graph") return "documents";
  if (pathname.startsWith("/projects")) return "projects";
  if (pathname.startsWith("/admin")) return "admin";
  if (pathname.startsWith("/account")) return "account";
  if (pathname.startsWith("/notifications")) return "notifications";
  return null;
}
