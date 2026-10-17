// Pure updates of the cached inbox pages from live events and local
// mutations. The list is a TanStack infinite query over the cursor, so the
// cache holds `InfiniteData<NotificationPage>`. The unread count is kept
// only in the summary query; a page's own `unread` is left as fetched.
import type { InfiniteData } from "@tanstack/react-query";
import type {
  NotificationFilter,
  NotificationItem,
  NotificationPage,
  NotificationSyncData,
} from "../../api/notificationTypes";

export type Inbox = InfiniteData<NotificationPage, string | null>;

/** Same objects back where nothing changed, so memoised rows (and the
 * list itself) skip the render. */
function mapPages(data: Inbox, fn: (item: NotificationItem) => NotificationItem | null): Inbox {
  let changed = false;
  const pages = data.pages.map((page) => {
    let pageChanged = false;
    const items: NotificationItem[] = [];
    for (const item of page.items) {
      const next = fn(item);
      if (next !== item) pageChanged = true;
      if (next) items.push(next);
    }
    if (!pageChanged) return page;
    changed = true;
    return { ...page, items };
  });
  return changed ? { ...data, pages } : data;
}

/** The server merges an unread entry with the next event of the same code
 * and asset (collapse key `{code}:{asset_id}`, ADR-0023 section 5) and
 * drops the old entry, so a collapsed item replaces its unread twin here. */
function replacedBy(item: NotificationItem, existing: NotificationItem): boolean {
  if (existing.id === item.id) return true;
  return (
    item.count > 1 &&
    !existing.read &&
    existing.code === item.code &&
    existing.asset !== null &&
    existing.asset.id === item.asset?.id
  );
}

/** A new entry from the stream goes to the top of the first page. */
export function withNotification(
  data: Inbox | undefined,
  item: NotificationItem,
  filter: NotificationFilter,
): Inbox | undefined {
  if (!data) return data;
  const pages = data.pages.map((page, i) => {
    const rest = page.items.filter((x) => !replacedBy(item, x));
    const items = i === 0 && (filter === "all" || !item.read) ? [item, ...rest] : rest;
    return { ...page, items };
  });
  return { ...data, pages };
}

/** Read flags, deletions and clearing, from a `sync` event or from the
 * response of this tab's own mutation. */
export function withSync(data: Inbox | undefined, sync: NotificationSyncData): Inbox | undefined {
  if (!data) return data;
  if (sync.cleared) {
    const first = data.pages[0];
    return {
      pages: first ? [{ ...first, items: [], next: null }] : [],
      pageParams: [data.pageParams[0] ?? null],
    };
  }
  if (!sync.read?.length && !sync.unread_ids?.length && !sync.deleted?.length && !sync.all_read) {
    return data;
  }
  const read = new Set(sync.read ?? []);
  const unreadIds = new Set(sync.unread_ids ?? []);
  const deleted = new Set(sync.deleted ?? []);
  return mapPages(data, (x) => {
    if (deleted.has(x.id)) return null;
    const next = unreadIds.has(x.id) ? false : sync.all_read || read.has(x.id) ? true : x.read;
    return next === x.read ? x : { ...x, read: next };
  });
}

/** Entries of all loaded pages, newest first. */
export function inboxItems(data: { pages: NotificationPage[] } | undefined): NotificationItem[] {
  return data ? data.pages.flatMap((p) => p.items) : [];
}
