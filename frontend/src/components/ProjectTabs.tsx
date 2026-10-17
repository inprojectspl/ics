import { t, type MessageKey } from "../lib/i18n";
import { PageTabs } from "./PageTabs";

export type ProjectTab = "files" | "members" | "map" | "hygiene" | "agent" | "settings";

type Audience = "member" | "maintainer" | "owner";

const TABS: ReadonlyArray<{ key: ProjectTab; path: string; label: MessageKey; audience: Audience }> = [
  { key: "files", path: "", label: "projectTabs.files", audience: "member" },
  { key: "members", path: "?tab=members", label: "projectTabs.members", audience: "member" },
  { key: "map", path: "/map", label: "projectTabs.map", audience: "member" },
  { key: "hygiene", path: "/hygiene", label: "projectTabs.hygiene", audience: "maintainer" },
  { key: "agent", path: "/agent", label: "projectTabs.agent", audience: "member" },
  { key: "settings", path: "?tab=settings", label: "projectTabs.settings", audience: "owner" },
];

export const PROJECT_TAB_LABEL = Object.fromEntries(TABS.map((x) => [x.key, x.label])) as Record<ProjectTab, MessageKey>;

interface Props {
  slug: string;
  tab: ProjectTab;
  /** Project member or admin; everyone else gets no tabs. */
  member: boolean;
  /** Owner, editor or admin: also sees the maintenance views. */
  canMaintain?: boolean;
  /** Owner or admin: also sees the settings. */
  isOwner?: boolean;
}

/** The sections of one project, local to it: documents first, then its
 * people, its map and its upkeep. */
export function ProjectTabs({ slug, tab, member, canMaintain = false, isOwner = false }: Props) {
  if (!member) return null;
  const allowed = (a: Audience) => a === "member" || (a === "maintainer" ? canMaintain : isOwner);
  const tabs = TABS.filter((x) => allowed(x.audience)).map((x) => ({
    key: x.key,
    href: `/projects/${slug}${x.path}`,
    label: t(x.label),
  }));
  return <PageTabs tabs={tabs} active={tab} ariaLabel={t("projectTabs.label")} className="mt-6" />;
}
