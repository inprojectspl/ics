import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { api, type ProjectDetail, type ProjectSummary } from "../../api";
import { AssetSortControl } from "../../components/AssetSortControl";
import { EmptyState } from "../../components/EmptyState";
import { Pagination } from "../../components/Pagination";
import { SearchInput } from "../../components/SearchInput";
import { ActiveFilterChips, DocumentFilters } from "../../components/documents/DocumentFilters";
import { DocumentList } from "../../components/documents/DocumentList";
import { Button } from "../../components/ui/Button";
import { PageToolbar } from "../../components/ui/PageToolbar";
import { sortAssets, type AssetSort } from "../../lib/assetSort";
import { t } from "../../lib/i18n";
import { qk } from "../../lib/queries";
import { useAssetFilter, type FilterKind } from "../../lib/useAssetFilter";
import { useDocTypeLabels } from "../../lib/useDocTypes";
import { useResettablePage } from "../../lib/useResettablePage";
import { KeyDocumentsList } from "./KeyDocuments";

const PAGE_SIZE = 25;
const KINDS: readonly FilterKind[] = ["type", "state", "source", "doctype", "fresh", "tag"];
const NO_PROJECTS = new Map<string, ProjectSummary>();

interface Props {
  project: ProjectDetail;
  sort: AssetSort;
  onSortChange: (s: AssetSort) => void;
  canContribute: boolean;
  onChanged: () => Promise<void>;
}

/** The project's documents, the main content of the project page: the key
 * reading list on top when the project has one, then the whole list. */
export function ProjectDocuments({ project, sort, onSortChange, canContribute, onChanged }: Props) {
  const [search, setSearch] = useState("");
  const { filters, toggleFilter, clearFilters, counts, visible: filtered } = useAssetFilter(project.assets, search);
  const docTypeLabels = useDocTypeLabels();
  const visible = useMemo(() => sortAssets(filtered, sort), [filtered, sort]);
  const keyDocs = useQuery({ queryKey: qk.keyDocuments(project.slug), queryFn: () => api.getKeyDocuments(project.slug) });

  const [page, setPage] = useResettablePage(JSON.stringify([filters, search, sort]));
  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const current = Math.min(page, pageCount);
  const rows = visible.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  const filterProps = { active: filters, counts, onToggle: toggleFilter, onClear: clearFilters, docTypeLabels, kinds: KINDS };

  if (project.assets.length === 0)
    return (
      <EmptyState
        icon={FileText}
        title={t("projectDetail.emptyTitle")}
        description={t(canContribute ? "projectDetail.emptyContrib" : "projectDetail.empty")}
      />
    );

  return (
    <div className="space-y-6">
      {keyDocs.data && keyDocs.data.length > 0 && <KeyDocumentsList docs={keyDocs.data} />}
      <section aria-label={t("projectTabs.files")}>
        <PageToolbar
          start={
            <>
              <SearchInput
                value={search}
                onChange={setSearch}
                placeholder={t("projectDetail.searchPlaceholder")}
                ariaLabel={t("projectDetail.searchPlaceholder")}
                className="min-w-0 basis-full sm:basis-auto sm:w-64 lg:w-72 xl:w-96"
              />
              <DocumentFilters {...filterProps} />
            </>
          }
          end={<AssetSortControl sort={sort} onChange={onSortChange} />}
          chips={<ActiveFilterChips {...filterProps} />}
        />
        <div className="mt-4">
          {visible.length === 0 ? (
            <EmptyState
              icon={FileText}
              title={t("homeEmpty.defaultTitle")}
              description={t("homeEmpty.defaultBody")}
              action={
                <Button
                  variant="secondary"
                  onClick={() => {
                    setSearch("");
                    clearFilters();
                  }}
                >
                  {t("filters.clear")}
                </Button>
              }
            />
          ) : (
            <DocumentList assets={rows} projectsById={NO_PROJECTS} onChanged={onChanged} sortKey={sort.key} hideProject />
          )}
          <Pagination page={current} pageSize={PAGE_SIZE} total={visible.length} onPage={setPage} />
          {project.assets_truncated && (
            <p className="mt-3 text-meta text-text-secondary">{t("projectDetail.truncated", { count: project.assets.length })}</p>
          )}
        </div>
      </section>
    </div>
  );
}
