import { describe, expect, it } from "vitest";
import { mkInbox, mkItem } from "../../test-notifications";
import { inboxItems, withNotification, withSync } from "./cache";

describe("withNotification", () => {
  it("puts a new entry on top of the first page", () => {
    const old = mkItem();
    const fresh = mkItem();
    const next = withNotification(mkInbox([old]), fresh, "all");
    expect(inboxItems(next).map((x) => x.id)).toEqual([fresh.id, old.id]);
  });

  it("replaces the unread twin of a collapsed entry, never a read one", () => {
    const asset = { id: "a1", slug: "s", title: "T", kind: "md_single" as const };
    const unreadTwin = mkItem({ asset });
    const readTwin = mkItem({ asset, read: true });
    const merged = mkItem({ asset, count: 3 });
    const next = withNotification(mkInbox([unreadTwin, readTwin]), merged, "all");
    expect(inboxItems(next).map((x) => x.id)).toEqual([merged.id, readTwin.id]);
  });

  it("keeps a read entry out of the unread list and leaves an unloaded list alone", () => {
    const read = mkItem({ read: true });
    expect(inboxItems(withNotification(mkInbox([]), read, "unread"))).toEqual([]);
    expect(withNotification(undefined, read, "all")).toBeUndefined();
  });
});

describe("withSync", () => {
  it("applies read, unread and deleted ids", () => {
    const a = mkItem();
    const b = mkItem({ read: true });
    const c = mkItem();
    const next = withSync(mkInbox([a, b, c]), { unread: 1, read: [a.id], unread_ids: [b.id], deleted: [c.id] });
    expect(inboxItems(next).map((x) => [x.id, x.read])).toEqual([
      [a.id, true],
      [b.id, false],
    ]);
  });

  it("marks everything read and clears the list", () => {
    const inbox = mkInbox([mkItem(), mkItem()], "next");
    expect(inboxItems(withSync(inbox, { unread: 0, all_read: true })).every((x) => x.read)).toBe(true);
    const cleared = withSync(inbox, { unread: 0, cleared: true });
    expect(cleared?.pages).toEqual([{ items: [], next: null }]);
    expect(withSync(undefined, { unread: 0 })).toBeUndefined();
  });

  it("keeps untouched data as the same objects (memoised rows skip the render)", () => {
    const a = mkItem();
    const b = mkItem({ read: true });
    const inbox = mkInbox([a]);
    expect(withSync(inbox, { unread: 1 })).toBe(inbox);
    expect(withSync(inbox, { unread: 1, read: ["other"] })).toBe(inbox);
    const next = withSync(mkInbox([a, b]), { unread: 0, read: [a.id] });
    expect(inboxItems(next)[1]).toBe(b);
    const two = { pages: [{ items: [a], next: "c" }, { items: [b], next: null }], pageParams: [null, "c"] };
    expect(withSync(two, { unread: 0, read: [a.id] })?.pages[1]).toBe(two.pages[1]);
  });
});
