import { CheckCheck, Settings } from "lucide-react";
import { t, tn } from "../../lib/i18n";
import { AppLink } from "../ui/AppLink";
import { iconButtonClass } from "../ui/IconButton";
import { useTooltip } from "../ui/Tooltip";
import { inboxItems } from "../../lib/notifications/cache";
import { useInbox } from "../../lib/notifications/queries";
import { useInboxActions } from "../../lib/notifications/useInboxActions";
import { useErrorToast } from "../Toast";
import { NotificationRow } from "./NotificationRow";

const LATEST = 5;
const LINK =
  "whitespace-nowrap text-meta text-text-secondary hover:text-accent transition-colors";

/**
 * The inbox popover of the global bar: the newest entries with
 * "mark all as read" and the way to the full list and the settings. Mounted
 * only while the menu is open, so the list is fetched on the first open (or
 * comes from the cache the live stream keeps current).
 */
export function MenuNotifications({ unread, onClose }: { unread: number; onClose: () => void }) {
  const onError = useErrorToast();
  const inbox = useInbox("all");
  const actions = useInboxActions(onError);
  const items = inboxItems(inbox.data).slice(0, LATEST);
  const title = t("notifications.title");
  const settingsTip = useTooltip(t("unsubscribe.settingsLink"), { side: "bottom" });

  return (
    <section aria-label={title}>
      <div className="flex items-center justify-between gap-3 pb-2 pl-1">
        <h2 className="flex items-center gap-2 whitespace-nowrap text-ui font-semibold text-text-primary">
          {/* The phone sheet already carries the title: the row says what is new. */}
          <span className="max-sm:sr-only">{title}</span>
          <span aria-hidden className="text-ui font-medium text-text-secondary sm:hidden">
            {unread > 0 ? tn("notifications.unreadCount", unread) : t("notifications.allRead")}
          </span>
          {unread > 0 && (
            <span className="inline-flex h-5 max-sm:hidden min-w-5 items-center justify-center rounded-full bg-accent-soft px-1.5 text-meta tabular-nums text-accent">
              {unread}
            </span>
          )}
        </h2>
        <AppLink
          href="/account/notifications"
          onClick={onClose}
          aria-label={t("unsubscribe.settingsLink")}
          {...settingsTip.triggerProps}
          className={iconButtonClass("ghost", "sm")}
        >
          <Settings size={16} aria-hidden />
        </AppLink>
        {settingsTip.bubble}
      </div>
      <div className="-mx-1.5">
        {inbox.isPending ? (
          <p className="px-3 py-4 text-center text-meta text-text-tertiary">{t("common.loading")}</p>
        ) : inbox.isError ? (
          <p role="alert" className="px-3 py-4 text-center text-meta text-danger">
            {t("notifications.loadError")}
          </p>
        ) : items.length === 0 ? (
          <p className="px-3 py-4 text-center text-meta text-text-tertiary">{t("notifications.emptyShort")}</p>
        ) : (
          <ul aria-label={t("notifications.latest")}>
            {items.map((item) => (
              <NotificationRow key={item.id} item={item} actions={actions} compact onOpened={onClose} />
            ))}
          </ul>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between gap-3 border-t border-border pl-1 pt-2">
        {unread > 0 ? (
          <button
            type="button"
            onClick={actions.markAllRead}
            className="-ml-1.5 inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-control px-1.5 text-meta font-medium text-accent transition-colors duration-150 hover:bg-accent-soft"
          >
            <CheckCheck size={14} aria-hidden />
            {t("notifications.markAllRead")}
          </button>
        ) : (
          <span />
        )}
        <AppLink href="/notifications" onClick={onClose} className={LINK}>
          {t("notifications.seeAll")}
        </AppLink>
      </div>
    </section>
  );
}
