import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { UploadCloud } from "lucide-react";
import { api, type AssetSort, Me, ProjectSummary } from "../api";
import { AssetListSkeleton } from "../components/AssetListSkeleton";
import { AssetSortControl } from "../components/AssetSortControl";
import { HomeEmptyState } from "../components/HomeEmptyState";
import { Pagination } from "../components/Pagination";
import { SearchInput } from "../components/SearchInput";
import { useToast } from "../components/Toast";
import { ActiveFilterChips, DocumentFilters } from "../components/documents/DocumentFilters";
import { DocumentList } from "../components/documents/DocumentList";
import { DropOverlay } from "../components/documents/DropOverlay";
import { UploadDialog } from "../components/documents/UploadDialog";
import { Page } from "../components/shell/Page";
import { PageContext } from "../components/shell/PageContext";
import { Button } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";
import { PageToolbar } from "../components/ui/PageToolbar";
import { formatApiError } from "../lib/apiError";
import { t, tn, type MessageKey } from "../lib/i18n";
import { qk, projectListQuery } from "../lib/queries";
import { useAssetFilterState, type AssetFilter, type AssetScope } from "../lib/useAssetFilter";
import { useAssetSort } from "../lib/useAssetSort";
import { useAssetUpload } from "../lib/useAssetUpload";
import { useDocTypeLabels } from "../lib/useDocTypes";
import { useDebouncedValue } from "../lib/useDebouncedValue";
import { canSearchDocuments } from "../lib/useDocumentSearch";
import { useResettablePage } from "../lib/useResettablePage";
import { useUploadMode } from "../lib/uploadMode";

const NO_PROJECTS: ProjectSummary[] = [];
// Search and filters apply to the whole corpus before the server cuts a page.
const PAGE_SIZE = 25;

const SCOPE_TITLE: Record<AssetScope, MessageKey> = {
  all: "nav.documents",
  "state:mine": "documents.mineTitle",
  "state:shared-with-me": "sidebarNav.sharedWithMe",
  "state:pinned": "sidebarNav.pinned",
  "admin:review": "home.filterReview",
};

type Props = { me: Me };

/** Opening `/?add=upload` (the command palette) starts with the upload dialog. */
function takeUploadRequest(): boolean {
  const params = new URLSearchParams(window.location.search);
  if (params.get("add") !== "upload") return false;
  params.delete("add");
  const qs = params.toString();
  window.history.replaceState({}, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
  return true;
}

/**
 * Documents: the list is on screen at once, with one heading, one primary
 * action (upload) and one toolbar row for finding and ordering. The scope
 * (all, mine, shared, favourites) is chosen in the sidebar; types, sharing,
 * source, projects and metadata are filters in the toolbar.
 */
export function Home({ me }: Props) {
  const [uploadMode, setUploadMode] = useUploadMode();
  const [uploadOpen, setUploadOpen] = useState(takeUploadRequest);
  const [search, setSearch] = useState("");
  const { sort, setSort } = useAssetSort("home", me.id);
  const [searchSort, setSearchSort] = useState<AssetSort | null>(null);
  const { scope, filters, toggleFilter, clearFilters } = useAssetFilterState();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const query = search.trim();
  const searching = query.length > 0;
  const shortQuery = searching && !canSearchDocuments(query);
  const debounced = useDebouncedValue(query, 250);
  const waiting = searching && query !== debounced;
  const activeSort = searching ? searchSort ?? undefined : sort;
  const [page, setPage] = useResettablePage(JSON.stringify([scope, filters, query, activeSort]));
  const assetsQuery = useQuery({
    queryKey: [...qk.assets(), "list", me.id, query, scope, filters, activeSort, page, PAGE_SIZE],
    queryFn: ({ signal }) => api.listAssets(page, PAGE_SIZE, activeSort, {
      q: searching ? query : undefined, scope, filters, facets: true, signal,
    }),
    // The raw query is in the key: typing immediately detaches and aborts
    // the previous request. No local results or previous-query placeholders.
    enabled: !shortQuery && !waiting,
    retry: false,
  });
  const projectsQuery = useQuery(projectListQuery);
  const projects = projectsQuery.data ?? NO_PROJECTS;
  const ready = !shortQuery && !waiting;
  const data = ready ? assetsQuery.data : undefined;
  const visible = data?.items ?? [];
  const total = data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  // A mutation or background refresh can remove the last row on this page.
  if (data && page > lastPage) setPage(lastPage);
  const counts = useMemo(
    () => new Map(Object.entries(data?.filter_counts ?? {}) as [AssetFilter, number][]),
    [data?.filter_counts],
  );
  const initialLoading = !shortQuery && (waiting || assetsQuery.isPending);
  const searchBusy = searching && !shortQuery && (waiting || assetsQuery.isFetching);
  const error = ready ? assetsQuery.error : null;
  const docTypeLabels = useDocTypeLabels();

  // Mutations mostly invalidate on their own; uploads (custom multipart)
  // and the row dialogs call this.
  const refresh = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.assets() }),
      queryClient.invalidateQueries({ queryKey: qk.quota() }),
      queryClient.invalidateQueries({ queryKey: qk.projects() }),
    ]);
  }, [queryClient]);

  useEffect(() => {
    const failed = [projectsQuery.error].find((e): e is Error => Boolean(e));
    if (failed) toast(formatApiError(failed, t("home.refreshFailed")), "error");
  }, [projectsQuery.error, toast]);

  const projectsById = useMemo(() => new Map(projects.map((p) => [p.id, p])), [projects]);
  const { uploading, onDrop, onPicked } = useAssetUpload({ uploadMode, onUploaded: refresh });

  const scopeTotal = data?.scope_counts?.[scope] ?? total;
  const narrowed = filters.length > 0 || search.trim().length > 0;
  const description = initialLoading
    ? " "
    : narrowed
      ? t("documents.countOf", { shown: total, total: tn("documents.count", scopeTotal) })
      : tn("documents.count", scopeTotal);
  const title = t(SCOPE_TITLE[scope]);

  const filterProps = {
    active: filters,
    counts,
    onToggle: toggleFilter,
    onClear: clearFilters,
    projects,
    docTypeLabels,
  };

  return (
    <>
      {scope !== "all" && <PageContext crumbs={[{ label: t("nav.documents"), href: "/" }, { label: title }]} />}
      <Page>
        <PageHeader
          title={title}
          description={description}
          actions={
            <Button icon={<UploadCloud size={16} aria-hidden />} onClick={() => setUploadOpen(true)}>
              {t("upload.action")}
            </Button>
          }
        />

        <PageToolbar
          start={
            <>
              <SearchInput
                value={search}
                onChange={setSearch}
                busy={searchBusy}
                inputProps={{ maxLength: 200 }}
                placeholder={t("home.searchPlaceholder")}
                className="min-w-0 basis-full sm:basis-auto sm:w-64 lg:w-72 xl:w-96"
              />
              <DocumentFilters {...filterProps} />
            </>
          }
          end={<AssetSortControl
            sort={activeSort ?? sort}
            onChange={searching ? setSearchSort : setSort}
            relevance={searching ? { active: searchSort === null, onSelect: () => setSearchSort(null) } : undefined}
          />}
          chips={<ActiveFilterChips {...filterProps} />}
        />

        <section aria-label={title} aria-busy={initialLoading || assetsQuery.isFetching} className="mt-4">
          {shortQuery ? (
            <p role="status" className="py-8 text-center text-ui text-text-secondary">{t("home.searchMinLength")}</p>
          ) : error ? (
            <div role="alert" className="space-y-3 py-8 text-center text-ui text-text-secondary">
              <p>{t("home.searchFailed")}</p>
              <Button variant="secondary" onClick={() => void assetsQuery.refetch()}>{t("common.retry")}</Button>
            </div>
          ) : initialLoading ? (
            <AssetListSkeleton />
          ) : visible.length === 0 ? (
            <HomeEmptyState
              scope={scope}
              search={search}
              filtered={filters.length > 0}
              onClearFilters={clearFilters}
            />
          ) : (
            <DocumentList assets={visible} projectsById={projectsById} onChanged={refresh} sortKey={activeSort?.key ?? "updated"} />
          )}
          {data && !error && <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPage={setPage} />}
        </section>
      </Page>

      <DropOverlay
        target={t("nav.documents")}
        audience={t(uploadMode === "public" ? "upload.modePublicBody" : "upload.modeOrgBody")}
        onDrop={(dt) => void onDrop(dt)}
        disabled={uploadOpen}
      />
      {uploadOpen && (
        <UploadDialog
          mode={uploadMode}
          onModeChange={setUploadMode}
          uploading={uploading}
          onPicked={onPicked}
          onDrop={onDrop}
          onClose={() => setUploadOpen(false)}
        />
      )}
    </>
  );
}
