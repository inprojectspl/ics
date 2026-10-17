import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, FolderOpen } from "lucide-react";
import { WATCHES_PAGE_SIZE, clearAssetWatch, clearProjectWatch, listWatches } from "../../api/notifications";
import type { WatchItem } from "../../api/notificationTypes";
import { Button } from "../../components/ui/Button";
import { Pagination } from "../../components/Pagination";
import { useErrorToast } from "../../components/Toast";
import { formatApiError } from "../../lib/apiError";
import { t, type MessageKey } from "../../lib/i18n";
import { qk } from "../../lib/queries";

const LEVEL_LABEL: Record<WatchItem["level"], MessageKey> = {
  watch: "accountNotifications.levelWatch",
  mute: "accountNotifications.levelMute",
  new: "projectWatch.new",
  all: "projectWatch.all",
};

function target(item: WatchItem): { key: string; name: string; href: string } {
  return item.type === "asset"
    ? { key: `asset:${item.asset.id}`, name: item.asset.title || item.asset.slug, href: `/v/${item.asset.slug}` }
    : { key: `project:${item.project.slug}`, name: item.project.name, href: `/projects/${item.project.slug}` };
}

function unwatch(item: WatchItem): Promise<unknown> {
  return item.type === "asset" ? clearAssetWatch(item.asset.id) : clearProjectWatch(item.project.slug);
}

/** Projects and documents the user watches or muted, paginated. */
export function WatchedItems() {
  const qc = useQueryClient();
  const onError = useErrorToast();
  const [page, setPage] = useState(1);
  const query = useQuery({ queryKey: qk.watches(page), queryFn: () => listWatches(page) });
  const items = query.data?.items ?? [];

  const onUnwatch = async (item: WatchItem) => {
    try {
      await unwatch(item);
    } catch (err) {
      onError(err);
    }
    void qc.invalidateQueries({ queryKey: qk.allWatches() });
  };

  if (query.isPending) return <p className="text-meta text-text-tertiary">{t("common.loading")}</p>;
  if (query.isError) {
    return (
      <p role="alert" className="text-ui text-danger">
        {formatApiError(query.error)}
      </p>
    );
  }
  if (items.length === 0) return <p className="text-meta text-text-tertiary">{t("accountNotifications.watchedEmpty")}</p>;

  return (
    <>
      <ul aria-label={t("accountNotifications.watchedTitle")} className="divide-y divide-border border-y border-border">
        {items.map((item) => {
          const dest = target(item);
          const Icon = item.type === "asset" ? FileText : FolderOpen;
          return (
            <li key={dest.key} className="flex items-center gap-3 py-2.5">
              <Icon size={16} aria-hidden className="shrink-0 text-text-tertiary" />
              <div className="min-w-0 flex-1">
                <a href={dest.href} className="block truncate text-ui text-text-primary hover:text-accent">
                  {dest.name}
                </a>
                <p className="text-meta text-text-tertiary">{t(LEVEL_LABEL[item.level])}</p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void onUnwatch(item)}
                aria-label={t("accountNotifications.unwatchLabel", { name: dest.name })}
              >
                {t("accountNotifications.unwatch")}
              </Button>
            </li>
          );
        })}
      </ul>
      <Pagination page={page} pageSize={WATCHES_PAGE_SIZE} total={query.data?.total ?? 0} onPage={setPage} />
    </>
  );
}
