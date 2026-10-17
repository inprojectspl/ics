import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import type { Me } from "../../api";
import { tn } from "../../lib/i18n";
import { qk } from "../../lib/queries";
import { renderWithClient } from "../../test-utils";
import { mkItem } from "../../test-notifications";
import { FakeEventSource, installStreamFakes, removeStreamFakes } from "../../test-stream-fakes";
import { ToastProvider } from "../Toast";
import { NotificationsButton } from "../shell/NotificationsButton";
import { NotificationStreamRoot } from "./NotificationStreamRoot";

const api = vi.hoisted(() => ({
  notificationSummary: vi.fn(),
  listNotifications: vi.fn(),
  STREAM_URL: "/api/notifications/stream",
  markRead: vi.fn(),
  markAllRead: vi.fn(),
  markUnread: vi.fn(),
  deleteNotification: vi.fn(),
  clearNotifications: vi.fn(),
}));
vi.mock("../../api/notifications", () => api);
vi.mock("../../api", () => ({ api: { me: vi.fn(), logout: vi.fn() } }));

const me = { id: "u1", email: "a@example.com", display_name: null, role: "user" } as Me;

beforeEach(() => {
  installStreamFakes({ locks: false });
  api.notificationSummary.mockReset().mockResolvedValue({ unread: 3 });
  api.listNotifications.mockReset().mockResolvedValue({ items: [mkItem({ at: "2026-09-01T10:00:00Z" })], next: null });
  document.title = "ICS";
});
afterEach(() => removeStreamFakes());

// Name of the bell with its unread count.
const bell = (n: number) => tn("notifications.openUnread", n);

function renderRoot(signedIn: boolean) {
  const view = renderWithClient(
    <ToastProvider>
      <NotificationStreamRoot />
      <NotificationsButton />
    </ToastProvider>,
  );
  if (signedIn) act(() => view.client.setQueryData(qk.me(), me));
  return view;
}

describe("NotificationStreamRoot", () => {
  it("stays idle until someone is signed in", () => {
    renderRoot(false);
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("feeds the bell badge, the tab title and a toast from the live stream", async () => {
    const view = renderRoot(true);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    await waitFor(() => expect(document.title).toBe("(3) ICS"));
    const item = mkItem({ code: "asset.created", asset: { id: "n", slug: "n", title: "Contract", kind: "pdf_doc" } });
    act(() => FakeEventSource.instances[0]?.emit("notification", { item, unread: 4 }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: bell(4) })).toBeInTheDocument(),
    );
    expect(await screen.findByText("New document Contract in CRM")).toBeInTheDocument();
    view.unmount();
    expect(FakeEventSource.instances[0]?.readyState).toBe(2);
  });

  it("puts a live entry at the top of the open inbox popover and raises the badge", async () => {
    renderRoot(true);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const button = await screen.findByRole("button", { name: bell(3) });
    act(() => button.click());
    const list = await screen.findByRole("list", { name: "Latest notifications" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);

    const item = mkItem({ asset: { id: "live", slug: "live", title: "Fresh report", kind: "md_single" } });
    act(() => FakeEventSource.instances[0]?.emit("notification", { item, unread: 4 }));
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(2));
    expect(within(list).getAllByRole("listitem")[0]).toHaveTextContent("Fresh report: new version 4");
    expect(screen.getByRole("button", { name: bell(4) })).toBeInTheDocument();
  });
});
