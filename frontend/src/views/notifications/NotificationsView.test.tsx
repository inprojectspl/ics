import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { NotificationItem } from "../../api/notificationTypes";
import { ToastProvider } from "../../components/Toast";
import { t } from "../../lib/i18n";
import { renderWithClient } from "../../test-utils";
import { mkItem } from "../../test-notifications";
import { NotificationsViewLazy } from "./lazy";
import { NotificationsView, groupByDay } from "./NotificationsView";

const api = vi.hoisted(() => ({
  notificationSummary: vi.fn(),
  listNotifications: vi.fn(),
  markRead: vi.fn(),
  markAllRead: vi.fn(),
  markUnread: vi.fn(),
  deleteNotification: vi.fn(),
  clearNotifications: vi.fn(),
}));
vi.mock("../../api/notifications", () => api);
const navigate = vi.fn();
vi.mock("../../lib/navigate", async (orig) => ({
  ...(await orig<typeof import("../../lib/navigate")>()),
  navigate: (p: string) => navigate(p),
}));
const confirm = vi.fn();
vi.mock("../../components/ConfirmDialog", () => ({ useConfirm: () => confirm }));

const DAY = 86_400_000;
const at = (msAgo: number) => new Date(Date.now() - msAgo).toISOString();

let items: NotificationItem[];

beforeEach(() => {
  items = [
    mkItem({ at: at(60_000), asset: { id: "a1", slug: "s1", title: "API spec", kind: "md_single" }, count: 10, link: "/v/s1/diff?from=4&to=13" }),
    mkItem({ at: at(DAY), code: "asset.created", read: true, actor: null, asset: { id: "a2", slug: "s2", title: "Contract", kind: "pdf_doc" } }),
    mkItem({ at: at(5 * DAY), unavailable: true, asset: null, project: null, link: null }),
    mkItem({ at: at(5 * DAY), code: "channel.chat_disabled", asset: null, project: null, actor: null, link: "/account/notifications" }),
  ];
  api.notificationSummary.mockReset().mockResolvedValue({ unread: 3 });
  api.listNotifications.mockReset().mockImplementation(async () => ({ items, next: null }));
  for (const fn of [api.markRead, api.markAllRead, api.markUnread, api.deleteNotification, api.clearNotifications]) {
    fn.mockReset().mockResolvedValue({ unread: 0 });
  }
  confirm.mockReset().mockResolvedValue(true);
  navigate.mockReset();
});

function renderView() {
  return renderWithClient(
    <ToastProvider>
      <NotificationsView />
    </ToastProvider>,
  );
}

const rows = () => screen.getAllByRole("listitem");
const MARK_ALL = /Mark all as read/;

function clear() {
  fireEvent.click(screen.getByRole("button", { name: "More notification actions" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Clear" }));
}

describe("NotificationsView", () => {
  it("loads lazily", async () => {
    renderWithClient(
      <ToastProvider>
        <Suspense fallback={<p>lazy-fallback</p>}>
          <NotificationsViewLazy />
        </Suspense>
      </ToastProvider>,
    );
    expect(await screen.findByRole("heading", { level: 1, name: "Notifications" })).toBeInTheDocument();
  });

  it("groups entries by day and builds one line per entry", async () => {
    renderView();
    expect(await screen.findByRole("region", { name: "Today" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Yesterday" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "API spec: 10 new versions" });
    expect(link).toHaveAttribute("href", "/v/s1/diff?from=4&to=13");
    expect(screen.getByRole("link", { name: "New document Contract in CRM" })).toBeInTheDocument();
    expect(screen.getByText("GitLab sync")).toBeInTheDocument();
    expect(screen.getAllByText("CRM").length).toBeGreaterThan(0);
    // Lost access: dimmed and not a link.
    const lost = screen.getByText("You no longer have access to this document").closest("li");
    expect(lost?.className).toContain("opacity-60");
    expect(within(lost as HTMLElement).queryByRole("link")).toBeNull();
    expect(screen.getByRole("link", { name: /Google Chat/ })).toHaveAttribute("href", "/account/notifications");
  });

  it("filters to unread entries on the server", async () => {
    renderView();
    await screen.findByRole("region", { name: "Today" });
    fireEvent.click(screen.getByRole("radio", { name: "Unread" }));
    await waitFor(() =>
      expect(api.listNotifications).toHaveBeenCalledWith({ before: null, filter: "unread" }),
    );
  });

  it("marks an entry read and unread, and deletes it, from its menu", async () => {
    renderView();
    await screen.findByRole("region", { name: "Today" });
    fireEvent.click(screen.getByRole("button", { name: "Actions: API spec: 10 new versions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Mark as read" }));
    expect(api.markRead).toHaveBeenCalledWith([items[0]?.id]);

    fireEvent.click(screen.getByRole("button", { name: "Actions: New document Contract in CRM" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Mark as unread" }));
    expect(api.markUnread).toHaveBeenCalledWith([items[1]?.id]);

    const before = rows().length;
    fireEvent.click(screen.getByRole("button", { name: "Actions: API spec: 10 new versions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(api.deleteNotification).toHaveBeenCalledWith(items[0]?.id);
    await waitFor(() => expect(rows()).toHaveLength(before - 1));
  });

  it("marks all read and clears the list after confirmation", async () => {
    renderView();
    await screen.findByRole("region", { name: "Today" });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: MARK_ALL })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: MARK_ALL }));
    expect(api.markAllRead).toHaveBeenCalled();

    clear();
    await waitFor(() => expect(api.clearNotifications).toHaveBeenCalled());
    expect(await screen.findByText("No notifications")).toBeInTheDocument();
  });

  it("keeps the list when the clear is cancelled and rolls back a failed change", async () => {
    confirm.mockResolvedValue(false);
    api.markAllRead.mockRejectedValue(new Error("boom"));
    renderView();
    await screen.findByRole("region", { name: "Today" });
    clear();
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(api.clearNotifications).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: MARK_ALL })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: MARK_ALL }));
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    await waitFor(() => expect(api.listNotifications.mock.calls.length).toBeGreaterThan(1));
  });

  it("loads older pages over the cursor", async () => {
    api.listNotifications.mockImplementation(async ({ before }: { before: string | null }) =>
      before ? { items: [mkItem({ at: at(9 * DAY) })], next: null } : { items, next: "c1" },
    );
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: "Show older" }));
    await waitFor(() => expect(api.listNotifications).toHaveBeenCalledWith({ before: "c1", filter: "all" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Show older" })).toBeNull());
  });

  it("keeps the header action short on a phone and reaches the settings from the menu", async () => {
    renderView();
    const markAll = await screen.findByRole("button", { name: MARK_ALL });
    expect(within(markAll).getByText(t("notifications.markAllReadShort")).className).toContain("sm:hidden");
    await waitFor(() => expect(screen.getByText("3 unread")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "More notification actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Settings" }));
    expect(navigate).toHaveBeenCalledWith("/account/notifications");
  });

  it("points to the watch controls when there is nothing", async () => {
    items = [];
    renderView();
    expect(await screen.findByText("No notifications")).toBeInTheDocument();
    expect(screen.getByText(/Watch a project or a document/)).toBeInTheDocument();
  });
});

describe("groupByDay", () => {
  it("names today and yesterday and dates the rest", () => {
    const now = new Date("2026-09-28T12:00:00Z");
    const groups = groupByDay(
      [
        mkItem({ at: "2026-09-28T08:00:00Z" }),
        mkItem({ at: "2026-09-28T07:00:00Z" }),
        mkItem({ at: "2026-09-27T20:00:00Z" }),
        mkItem({ at: "2026-09-01T10:00:00Z" }),
      ],
      now,
    );
    expect(groups.map((g) => [g.label, g.items.length])).toEqual([
      ["Today", 2],
      ["Yesterday", 1],
      ["September 1, 2026", 1],
    ]);
  });
});
