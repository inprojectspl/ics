import { memo, type MouseEvent } from "react";
import { clsx } from "clsx";
import { Mail, MailOpen, MoreHorizontal, Trash2 } from "lucide-react";
import type { NotificationItem } from "../../api/notificationTypes";
import { formatDateTime, formatRelative } from "../../lib/format";
import { t } from "../../lib/i18n";
import { isPlainClick, navigate } from "../../lib/navigate";
import type { InboxActions } from "../../lib/notifications/useInboxActions";
import { iconButtonClass } from "../ui/IconButton";
import { Menu } from "../ui/Menu";
import {
  NOTIFICATION_ICON,
  NotificationText,
  actorLabel,
  notificationPlainText,
} from "./notificationText";

interface Props {
  item: NotificationItem;
  actions: InboxActions;
  /** Popover variant: no project chip and no trailing menu. */
  compact?: boolean;
  /** Called after the row is opened (the popover closes itself). */
  onOpened?: () => void;
}

/**
 * One inbox entry. The whole row is the link (a stretched anchor), at least
 * 48 px high; opening it marks it read. An entry the user lost access to is
 * dimmed and leads nowhere.
 */
function NotificationRowImpl({ item, actions, compact = false, onOpened }: Props) {
  const Icon = NOTIFICATION_ICON[item.code];
  // The server nulls the link of an entry the user lost access to.
  const href = item.link;
  const actor = actorLabel(item);
  const text = <NotificationText item={item} />;

  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    actions.markOpened(item);
    onOpened?.();
    if (href && isPlainClick(e)) {
      e.preventDefault();
      navigate(href);
    }
  };

  return (
    <li
      className={clsx(
        "relative flex items-start gap-3 min-h-12 px-3 py-2.5 rounded-control transition-colors",
        href && "hover:bg-surface-subtle/70 focus-within:bg-surface-subtle/70",
        item.unavailable && "opacity-60",
      )}
    >
      <span
        aria-hidden
        className={clsx(
          "mt-0.5 grid place-items-center size-8 shrink-0 rounded-control",
          item.read ? "bg-surface-subtle text-text-tertiary" : "bg-accent/12 text-accent",
        )}
      >
        <Icon size={16} />
      </span>
      <div className="min-w-0 flex-1">
        <p className={clsx("text-ui leading-snug break-words", item.read ? "text-text-secondary" : "text-text-primary")}>
          {href ? (
            <a
              href={href}
              onClick={onClick}
              className="after:absolute after:inset-0 after:rounded-control focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-accent/40"
            >
              {text}
            </a>
          ) : (
            text
          )}
        </p>
        <div className="mt-1 flex items-center gap-x-2 gap-y-1 flex-wrap text-meta text-text-tertiary">
          {!compact && item.project && (
            <span className="max-w-[12rem] truncate px-2 py-0.5 rounded-full bg-text-primary/[0.05] text-text-secondary">
              {item.project.name}
            </span>
          )}
          {actor && <span className="truncate max-w-[14rem]">{actor}</span>}
          <time dateTime={item.at} title={formatDateTime(item.at) ?? undefined} className="whitespace-nowrap">
            {formatRelative(item.at)}
          </time>
        </div>
      </div>
      {!item.read && (
        <span className="mt-2 size-2 shrink-0 rounded-full bg-accent">
          <span className="sr-only">{t("notifications.unreadMark")}</span>
        </span>
      )}
      {!compact && (
        <div className="relative z-10 -my-1 -mr-1 shrink-0">
          <Menu
            label={t("notifications.rowMenu", { text: notificationPlainText(item) })}
            actions={[
              item.read
                ? { key: "unread", label: t("notifications.markUnread"), icon: Mail, onClick: () => actions.toggleRead(item) }
                : { key: "read", label: t("notifications.markRead"), icon: MailOpen, onClick: () => actions.toggleRead(item) },
              { key: "delete", label: t("common.delete"), icon: Trash2, danger: true, onClick: () => actions.remove(item) },
            ]}
            trigger={(props) => (
              <button
                type="button"
                {...props}
                aria-label={t("notifications.rowMenu", { text: notificationPlainText(item) })}
                title={t("notifications.rowMenuTitle")}
                className={iconButtonClass("ghost")}
              >
                <MoreHorizontal size={18} aria-hidden />
              </button>
            )}
          />
        </div>
      )}
    </li>
  );
}

export const NotificationRow = memo(NotificationRowImpl);
