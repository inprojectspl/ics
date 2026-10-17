import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BellOff, CheckCheck, MoreHorizontal, Settings, Trash2 } from "lucide-react";
import type { NotificationFilter, NotificationItem } from "../../api/notificationTypes";
import { useConfirm } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { LoadingListSkeleton } from "../../components/LoadingListSkeleton";
import { NotificationRow } from "../../components/notifications/NotificationRow";
import { SegmentedToggle } from "../../components/SegmentedToggle";
import { Page } from "../../components/shell/Page";
import { useErrorToast } from "../../components/Toast";
import { Button } from "../../components/ui/Button";
import { iconButtonClass } from "../../components/ui/IconButton";
import { Menu } from "../../components/ui/Menu";
import type { MenuAction } from "../../components/ui/menuAction";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatApiError } from "../../lib/apiError";
import { formatDayHeading } from "../../lib/format";
import { t, tn } from "../../lib/i18n";
import { navigate } from "../../lib/navigate";
import { inboxItems } from "../../lib/notifications/cache";
import { useInbox, useUnreadCount } from "../../lib/notifications/queries";
import { useInboxActions } from "../../lib/notifications/useInboxActions";
import { useDocumentTitle } from "../../lib/useDocumentTitle";

interface DayGroup {
  key: string;
  label: string;
  items: NotificationItem[];
}

function localDay(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

/** Entries grouped by local day, newest first. */
export function groupByDay(items: NotificationItem[], now: Date = new Date()): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const item of items) {
    const key = localDay(new Date(item.at));
    let group = groups.at(-1);
    if (!group || group.key !== key) {
      group = { key, label: formatDayHeading(item.at, now), items: [] };
      groups.push(group);
    }
    group.items.push(item);
  }
  return groups;
}

/** Loads the next page when the sentinel under the list comes into view. */
function useLoadMore(enabled: boolean, load: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) load();
    }, { rootMargin: "400px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [enabled, load]);
  return ref;
}

export function NotificationsView() {
  const [filter, setFilter] = useState<NotificationFilter>("all");
  const confirm = useConfirm();
  const unread = useUnreadCount() ?? 0;
  const inbox = useInbox(filter);
  const onError = useErrorToast();
  const actions = useInboxActions(onError);
  useDocumentTitle(t("notifications.title"));

  const items = useMemo(() => inboxItems(inbox.data), [inbox.data]);
  const groups = useMemo(() => groupByDay(items), [items]);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = inbox;
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  const sentinel = useLoadMore(Boolean(hasNextPage), loadMore);

  const onClear = async () => {
    const ok = await confirm({
      title: t("notifications.clearTitle"),
      message: t("notifications.clearBody"),
      confirmLabel: t("notifications.clear"),
      destructive: true,
    });
    if (ok) actions.clearAll();
  };

  const more: MenuAction[] = [
    { key: "settings", label: t("notifications.settingsLink"), icon: Settings, onClick: () => navigate("/account/notifications") },
    { key: "clear", label: t("notifications.clear"), icon: Trash2, danger: true, disabled: items.length === 0, onClick: () => void onClear() },
  ];

  return (
    <Page width="form">
      <PageHeader
        title={t("notifications.title")}
        description={unread > 0 ? tn("notifications.unreadCount", unread) : t("notifications.allRead")}
        actions={
          <>
            <Button
              variant="secondary"
              icon={<CheckCheck size={16} aria-hidden />}
              onClick={actions.markAllRead}
              disabled={unread === 0}
              aria-label={t("notifications.markAllRead")}
              title={t("notifications.markAllRead")}
            >
              <span className="sm:hidden">{t("notifications.markAllReadShort")}</span>
              <span className="hidden sm:inline">{t("notifications.markAllRead")}</span>
            </Button>
            <Menu
              label={t("notifications.more")}
              actions={more}
              trigger={(props) => (
                <button type="button" {...props} aria-label={t("notifications.more")} className={iconButtonClass("secondary")}>
                  <MoreHorizontal size={18} aria-hidden />
                </button>
              )}
            />
          </>
        }
      />
      <div className="mb-4">
        <SegmentedToggle
          ariaLabel={t("notifications.filterLabel")}
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: t("notifications.filterAll") },
            { value: "unread", label: t("notifications.filterUnread") },
          ]}
        />
      </div>

      {inbox.isPending ? (
        <LoadingListSkeleton rows={5} />
      ) : inbox.isError ? (
        <EmptyState icon={BellOff} title={t("notifications.loadError")} description={formatApiError(inbox.error)} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={BellOff}
          title={filter === "unread" ? t("notifications.emptyUnread") : t("notifications.empty")}
          description={t("notifications.emptyHint")}
        />
      ) : (
        <div className="space-y-6">
          {groups.map((group) => (
            <section key={group.key} aria-label={group.label}>
              <h2 className="mb-2 text-meta font-semibold text-text-secondary">{group.label}</h2>
              <div className="overflow-hidden rounded-card border border-border bg-surface shadow-card">
                <ul className="divide-y divide-border">
                  {group.items.map((item) => (
                    <NotificationRow key={item.id} item={item} actions={actions} />
                  ))}
                </ul>
              </div>
            </section>
          ))}
          <div ref={sentinel} />
          {hasNextPage && (
            <div className="flex justify-center">
              <Button variant="secondary" onClick={loadMore} busy={isFetchingNextPage}>
                {isFetchingNextPage ? t("common.loading") : t("notifications.loadOlder")}
              </Button>
            </div>
          )}
        </div>
      )}
    </Page>
  );
}
