import { Fragment, type ReactNode } from "react";
import {
  FilePen,
  FilePlus2,
  FolderInput,
  MessageSquareWarning,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import type { NotificationCode, NotificationItem } from "../../api/notificationTypes";
import { t, tn } from "../../lib/i18n";

export const NOTIFICATION_ICON: Record<NotificationCode, LucideIcon> = {
  "asset.created": FilePlus2,
  "asset.added": FolderInput,
  "asset.updated": FilePen,
  "asset.deleted": Trash2,
  "channel.chat_disabled": MessageSquareWarning,
};

const TITLE = "{title}";

/** Catalogue text of an entry with `{title}` left in place, so the title
 * can be set in bold without building the sentence from fragments. */
function template(item: NotificationItem): string {
  if (item.unavailable) return t("notifications.text.unavailable");
  const project = item.project?.name;
  switch (item.code) {
    case "asset.created":
      return project ? t("notifications.text.created", { project }) : t("notifications.text.createdNoProject");
    case "asset.added":
      return project ? t("notifications.text.added", { project }) : t("notifications.text.addedNoProject");
    case "asset.updated":
      if (item.count > 1) return tn("notifications.text.updatedMany", item.count);
      return item.version === null
        ? t("notifications.text.updatedOne")
        : t("notifications.text.updated", { version: item.version });
    case "asset.deleted":
      return t("notifications.text.deleted");
    case "channel.chat_disabled":
      return t("notifications.text.chatDisabled");
  }
}

function titleOf(item: NotificationItem): string {
  return item.asset?.title || item.asset?.slug || t("notifications.untitled");
}

/** One line of text, for toasts and accessible names. */
export function notificationPlainText(item: NotificationItem): string {
  return template(item).split(TITLE).join(titleOf(item));
}

/** The same line with the document title in bold. */
export function NotificationText({ item }: { item: NotificationItem }): ReactNode {
  const parts = template(item).split(TITLE);
  const title = titleOf(item);
  return parts.map((part, i) => (
    <Fragment key={i}>
      {i > 0 && <strong className="font-semibold text-text-primary">{title}</strong>}
      {part}
    </Fragment>
  ));
}

/** Who caused the entry; a CI binding sync has no user. */
export function actorLabel(item: NotificationItem): string | null {
  if (item.code === "channel.chat_disabled") return null;
  return item.actor?.name ?? t("notifications.systemActor");
}
