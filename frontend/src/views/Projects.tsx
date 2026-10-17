import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownAZ, CalendarPlus, ChevronDown, Files, FolderKanban, Plus, Users } from "lucide-react";
import type { ProjectSummary } from "../api";
import { EmptyState } from "../components/EmptyState";
import { LoadingListSkeleton } from "../components/LoadingListSkeleton";
import { Pagination } from "../components/Pagination";
import { SearchInput } from "../components/SearchInput";
import { CreateProjectDialog } from "../components/projects/CreateProjectDialog";
import { ProjectRow } from "../components/projects/ProjectRow";
import { Page } from "../components/shell/Page";
import { Button, buttonClass } from "../components/ui/Button";
import { DataList } from "../components/ui/DataList";
import { Menu } from "../components/ui/Menu";
import { PageHeader } from "../components/ui/PageHeader";
import { PageToolbar } from "../components/ui/PageToolbar";
import { formatApiError } from "../lib/apiError";
import { nameCollator, t, tn, type MessageKey } from "../lib/i18n";
import { qk, projectListQuery } from "../lib/queries";
import { useResettablePage } from "../lib/useResettablePage";

const PAGE_SIZE = 25;
const NO_PROJECTS: ProjectSummary[] = [];

type ProjectSort = "name" | "created" | "documents";
type RoleFilter = "all" | "owner" | "member";

const SORTS: ReadonlyArray<{ key: ProjectSort; label: MessageKey; icon: typeof Files }> = [
  { key: "name", label: "projects.sortName", icon: ArrowDownAZ },
  { key: "created", label: "projects.sortCreated", icon: CalendarPlus },
  { key: "documents", label: "projects.sortDocuments", icon: Files },
];

const ROLES: ReadonlyArray<{ key: RoleFilter; label: MessageKey }> = [
  { key: "all", label: "projects.roleAll" },
  { key: "owner", label: "projects.roleOwned" },
  { key: "member", label: "projects.roleMember" },
];

/** `/projects?new=1` (the command palette) opens the create dialog. */
function takeCreateRequest(): boolean {
  const params = new URLSearchParams(window.location.search);
  if (params.get("new") !== "1") return false;
  window.history.replaceState({}, "", window.location.pathname);
  return true;
}

/**
 * Projects: a dense list where the name, what it is about, its size, its
 * people and your role fit one row. One primary action (new project) and
 * one toolbar (search, whose projects, order).
 */
export function Projects() {
  const [creating, setCreating] = useState(takeCreateRequest);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<ProjectSort>("name");
  const [role, setRole] = useState<RoleFilter>("all");
  const queryClient = useQueryClient();

  // The same query as the sidebar's project list, so both read one cache.
  const query = useQuery({
    ...projectListQuery,
  });
  const projects = query.data ?? NO_PROJECTS;

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const collator = nameCollator();
    return projects
      // "member" means a membership without ownership; an admin also lists
      // projects they are not a member of (my_role null), which only "all" shows.
      .filter((p) =>
        role === "all" ? true : role === "owner" ? p.my_role === "owner" : p.my_role === "editor" || p.my_role === "viewer",
      )
      .filter((p) => !q || p.name.toLowerCase().includes(q) || (p.description ?? "").toLowerCase().includes(q))
      .sort((a, b) =>
        sort === "created"
          ? b.created_at.localeCompare(a.created_at)
          : sort === "documents"
            ? b.asset_count - a.asset_count || collator.compare(a.name, b.name)
            : collator.compare(a.name, b.name),
      );
  }, [projects, search, sort, role]);

  const [page, setPage] = useResettablePage(JSON.stringify([search, sort, role]));
  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const current = Math.min(page, pageCount);
  const pageItems = visible.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  const sortLabel = t(SORTS.find((s) => s.key === sort)?.label ?? "projects.sortName");
  const roleLabel = t(ROLES.find((r) => r.key === role)?.label ?? "projects.roleAll");

  return (
    <Page>
      <PageHeader
        title={t("projects.title")}
        description={query.isPending ? " " : tn("projects.count", projects.length)}
        actions={
          <Button icon={<Plus size={16} aria-hidden />} onClick={() => setCreating(true)}>
            {t("projects.newProject")}
          </Button>
        }
      />

      {projects.length > 0 && (
        <PageToolbar
          start={
            <>
              <SearchInput
                value={search}
                onChange={setSearch}
                placeholder={t("projects.searchPlaceholder")}
                ariaLabel={t("projects.searchPlaceholder")}
                className="min-w-0 basis-full sm:basis-auto sm:w-64 lg:w-72 xl:w-96"
              />
              <Menu
                label={t("projects.roleFilter")}
                align="start"
                actions={ROLES.map((r) => ({
                  key: r.key,
                  label: t(r.label),
                  checked: r.key === role,
                  onClick: () => setRole(r.key),
                }))}
                trigger={(props) => (
                  <button
                    type="button"
                    {...props}
                    aria-label={`${t("projects.roleFilter")}: ${roleLabel}`}
                    className={buttonClass("secondary")}
                  >
                    <Users size={16} aria-hidden className="text-text-secondary" />
                    <span className="max-sm:sr-only">{roleLabel}</span>
                    <ChevronDown size={14} aria-hidden className="text-text-secondary" />
                  </button>
                )}
              />
            </>
          }
          end={
            <Menu
              label={t("assetSort.menuLabel")}
              actions={SORTS.map((s) => ({
                key: s.key,
                label: t(s.label),
                icon: s.icon,
                checked: s.key === sort,
                onClick: () => setSort(s.key),
              }))}
              trigger={(props) => (
                <button
                  type="button"
                  {...props}
                  aria-label={t("assetSort.triggerLabel", { key: sortLabel })}
                  className={buttonClass("secondary")}
                >
                  <ArrowDownAZ size={16} aria-hidden className="text-text-secondary" />
                  <span className="hidden text-text-secondary md:inline">{t("assetSort.prefix")}</span>
                  <span className="max-sm:sr-only">{sortLabel}</span>
                  <ChevronDown size={14} aria-hidden className="text-text-secondary" />
                </button>
              )}
            />
          }
        />
      )}

      <section aria-label={t("projects.title")} className="mt-4">
        {query.isPending ? (
          <LoadingListSkeleton rows={5} />
        ) : query.isError ? (
          <EmptyState
            icon={FolderKanban}
            title={t("projects.loadFailed")}
            description={formatApiError(query.error)}
            action={
              <Button variant="secondary" onClick={() => void query.refetch()}>
                {t("common.retry")}
              </Button>
            }
          />
        ) : projects.length === 0 ? (
          <EmptyState
            icon={FolderKanban}
            title={t("projects.emptyTitle")}
            description={t("projects.emptyBody")}
          />
        ) : visible.length === 0 ? (
          <EmptyState
            icon={FolderKanban}
            title={t("projects.noMatchesTitle")}
            description={t("projects.noMatchesBody")}
            action={
              <Button
                variant="secondary"
                onClick={() => {
                  setSearch("");
                  setRole("all");
                }}
              >
                {t("filters.clear")}
              </Button>
            }
          />
        ) : (
          <>
            <DataList label={t("projects.title")}>
              {pageItems.map((p) => (
                <ProjectRow key={p.id} project={p} />
              ))}
            </DataList>
            <Pagination page={current} pageSize={PAGE_SIZE} total={visible.length} onPage={setPage} />
          </>
        )}
      </section>

      {creating && (
        <CreateProjectDialog
          onClose={() => setCreating(false)}
          onCreated={() => void queryClient.invalidateQueries({ queryKey: qk.projects() })}
        />
      )}
    </Page>
  );
}
