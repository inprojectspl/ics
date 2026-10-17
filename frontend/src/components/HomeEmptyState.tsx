import { Files, Inbox, ListFilter, Search, ShieldAlert, Star, Users } from "lucide-react";
import { t } from "../lib/i18n";
import type { AssetScope } from "../lib/useAssetFilter";
import { EmptyState } from "./EmptyState";
import { Button } from "./ui/Button";

interface Props {
  scope: AssetScope;
  search: string;
  /** Toolbar filters are on: the way out is clearing them. */
  filtered: boolean;
  onClearFilters: () => void;
}

/** Empty document list: the most concrete reason first (search, filters,
 * then the scope), each with the action that gets the person further. */
export function HomeEmptyState({ scope, search, filtered, onClearFilters }: Props) {
  const q = search.trim();
  if (q.length >= 2)
    return (
      <EmptyState
        icon={Search}
        title={t("homeEmpty.noResultsTitle", { query: q })}
        description={t("homeEmpty.noResultsBody")}
      />
    );
  if (q.length > 0)
    return <EmptyState icon={Search} title={t("homeEmpty.noMatchesTitle")} description={t("homeEmpty.noMatchesBody")} />;
  if (filtered)
    return (
      <EmptyState
        icon={ListFilter}
        title={t("homeEmpty.defaultTitle")}
        description={t("homeEmpty.defaultBody")}
        action={
          <Button variant="secondary" onClick={onClearFilters}>
            {t("filters.clear")}
          </Button>
        }
      />
    );
  switch (scope) {
    case "all":
    case "state:mine":
      return (
        <EmptyState
          icon={Inbox}
          title={t("homeEmpty.allTitle")}
          description={t("homeEmpty.allBody")}
        />
      );
    case "state:pinned":
      return <EmptyState icon={Star} title={t("homeEmpty.pinnedTitle")} description={t("homeEmpty.pinnedBody")} />;
    case "state:shared-with-me":
      return <EmptyState icon={Users} title={t("homeEmpty.sharedTitle")} description={t("homeEmpty.sharedBody")} />;
    case "admin:review":
      return <EmptyState icon={ShieldAlert} title={t("homeEmpty.reviewTitle")} description={t("homeEmpty.reviewBody")} />;
    default:
      return <EmptyState icon={Files} title={t("homeEmpty.defaultTitle")} description={t("homeEmpty.defaultBody")} />;
  }
}
