import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { AdminUser, Me } from "../api";
import { ApiError } from "../api/_core";
import { setLocale, t } from "../lib/i18n";
import { AdminUsers } from "./AdminUsers";

const adminUsersList = vi.fn();
const adminUserGet = vi.fn();

vi.mock("../api", () => ({
  api: {
    adminUsersList: (...a: unknown[]) => adminUsersList(...a),
    adminUserGet: (...a: unknown[]) => adminUserGet(...a),
  },
}));
// Both dialogs have their own logic and API calls; the view only owns
// opening them and reacting to their callbacks.
vi.mock("../components/InviteUserDialog", () => ({
  InviteUserDialog: (p: { onClose: () => void; onCreated: () => Promise<void> }) => (
    <div data-testid="invite">
      <button onClick={p.onClose}>invite-close</button>
      <button onClick={() => void p.onCreated()}>invite-created</button>
    </div>
  ),
}));
vi.mock("../components/UserDetailDialog", () => ({
  UserDetailDialog: (p: {
    user: AdminUser;
    onClose: () => void;
    onChanged: () => Promise<void>;
    onDeleted: () => Promise<void>;
  }) => (
    <div data-testid="detail">
      <span>detail:{p.user.email}:{p.user.display_name}</span>
      <button onClick={p.onClose}>detail-close</button>
      <button onClick={() => void p.onChanged()}>detail-changed</button>
      <button onClick={() => void p.onDeleted()}>detail-deleted</button>
    </div>
  ),
}));

const admin = { id: "u", email: "a@example.com", display_name: null, role: "admin" } as Me;

const NOW = Date.now();
const ago = (ms: number) => new Date(NOW - ms).toISOString();

function user(over: Partial<AdminUser> = {}): AdminUser {
  return {
    id: "u1",
    email: "alice@example.com",
    display_name: null,
    role: "user",
    auth_method: "password",
    email_verified: true,
    email_verified_at: null,
    locked_until: null,
    locked: false,
    storage_quota_bytes: 1000,
    bundle_max_bytes: 100,
    html_autobypass: false,
    asset_count: 1,
    asset_bytes: 500,
    created_at: "2026-01-01T00:00:00Z",
    last_login_at: null,
    ...over,
  };
}

function page(users: AdminUser[], over: Record<string, unknown> = {}) {
  return {
    summary: { total: 60, active_30d: 10, locked: 1, unverified: 2, admins: 3 },
    users,
    total: users.length,
    page: 1,
    page_size: 25,
    ...over,
  };
}

const users = [
  user({ id: "u1", email: "alice@example.com", display_name: "Alice Smith", last_login_at: ago(5 * 60_000) }),
  user({
    id: "u2",
    email: "ext@example.org",
    role: "external",
    auth_method: "google_sso",
    locked: true,
    email_verified: false,
    asset_count: 3,
    last_login_at: ago(5 * 3_600_000),
  }),
  user({
    id: "u3",
    email: "boss@example.com",
    display_name: "boss",
    role: "admin",
    asset_count: 7,
    storage_quota_bytes: 0,
    last_login_at: ago(3 * 86_400_000),
  }),
  user({ id: "u4", email: "old@example.com", asset_count: 0, last_login_at: "2025-01-15T10:00:00Z", auth_method: "invite" }),
];

function pickRole(name: string) {
  fireEvent.click(screen.getByRole("button", { name: /^Filter by role:/ }));
  fireEvent.click(screen.getByRole("menuitemradio", { name }));
}

function lastParams() {
  return adminUsersList.mock.calls.at(-1)?.[0] as Record<string, unknown>;
}

beforeEach(() => {
  window.history.replaceState({}, "", "/admin/users");
  adminUsersList.mockReset().mockResolvedValue(page(users));
  adminUserGet.mockReset();
});

describe("AdminUsers", () => {
  it("renders in Polish with Polish plurals", async () => {
    setLocale("pl", { persist: false });
    render(<AdminUsers me={admin} />);
    expect(await screen.findByRole("button", { name: "Alice Smith" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Użytkownicy" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Aktywni \(30 dni\)/ })).toBeInTheDocument();
    expect(screen.getByText("Konta: 60 · administratorzy: 3")).toBeInTheDocument();
    expect(screen.getAllByText(/1 dokument ·/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/3 dokumenty ·/).length).toBeGreaterThan(0);
    expect(screen.getByText(/^ostatnio: 5 minut temu$/)).toBeInTheDocument();
  });

  it("denies non-admins without fetching", () => {
    render(<AdminUsers me={{ ...admin, role: "user" }} />);
    expect(screen.getByText("No access")).toBeInTheDocument();
    expect(adminUsersList).not.toHaveBeenCalled();
  });

  it("shows the load error", async () => {
    adminUsersList.mockRejectedValue(new ApiError(503, "db down", "db down", "service_unavailable"));
    render(<AdminUsers me={admin} />);
    expect(await screen.findByText("Server error. Try again.")).toBeInTheDocument();
  });

  it("shows the empty list message", async () => {
    adminUsersList.mockResolvedValue(page([]));
    render(<AdminUsers me={admin} />);
    expect(await screen.findByText("No users match the filters.")).toBeInTheDocument();
  });

  it("renders rows with badges, counts, quota and last login times", async () => {
    render(<AdminUsers me={admin} />);
    expect(await screen.findByRole("button", { name: "Alice Smith" })).toBeInTheDocument();
    expect(adminUsersList).toHaveBeenCalledWith({
      q: undefined,
      role: undefined,
      status: undefined,
      page: 1,
      page_size: 25,
    });
    // Named users show the e-mail underneath; the rest are named by it.
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ext@example.org" })).toBeInTheDocument();
    // display_name equal to the email local part is not repeated
    expect(screen.getByRole("button", { name: "boss@example.com" })).toBeInTheDocument();
    expect(screen.getByText("locked")).toBeInTheDocument();
    expect(screen.getByText("unverified")).toBeInTheDocument();
    expect(screen.getByText("Google")).toBeInTheDocument();
    expect(screen.getByText(t("adminUsers.authInvite"))).toBeInTheDocument();
    expect(screen.getByText("External client")).toBeInTheDocument();
    expect(screen.getAllByText(/7 documents ·/).length).toBeGreaterThan(0);
    const bars = screen.getAllByRole("progressbar");
    expect(bars.map((b) => b.getAttribute("aria-valuenow"))).toEqual(["50", "50", "0", "50"]);
    expect(screen.getByText("last seen: 5 minutes ago")).toBeInTheDocument();
    expect(screen.getByText("last seen: 3 days ago")).toBeInTheDocument();
    expect(screen.getByText("Accounts: 60 · administrators: 3")).toBeInTheDocument();
  });

  it("filters by status chip and role", async () => {
    render(<AdminUsers me={admin} />);
    await screen.findByRole("button", { name: "Alice Smith" });
    fireEvent.click(screen.getByRole("button", { name: /Locked/ }));
    await waitFor(() => expect(lastParams()).toMatchObject({ status: "locked" }));
    pickRole("External client");
    await waitFor(() => expect(lastParams()).toMatchObject({ role: "external", status: "locked" }));
    fireEvent.click(screen.getByRole("button", { name: /All/ }));
    pickRole("Any role");
    await waitFor(() => expect(lastParams()).toMatchObject({ role: undefined, status: undefined }));
  });

  it("debounces the search into a trimmed query", async () => {
    render(<AdminUsers me={admin} />);
    await screen.findByRole("button", { name: "Alice Smith" });
    const calls = adminUsersList.mock.calls.length;
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "  alice " } });
    expect(adminUsersList).toHaveBeenCalledTimes(calls);
    await waitFor(() => expect(lastParams()).toMatchObject({ q: "alice", page: 1 }));
  });

  it("pages through results", async () => {
    adminUsersList.mockResolvedValue(page(users, { total: 60 }));
    render(<AdminUsers me={admin} />);
    await screen.findByRole("button", { name: "Alice Smith" });
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(lastParams()).toMatchObject({ page: 2 }));
  });

  it("goes back to page 1 on a filter change without querying the old page", async () => {
    adminUsersList.mockResolvedValue(page(users, { total: 60 }));
    render(<AdminUsers me={admin} />);
    await screen.findByRole("button", { name: "Alice Smith" });
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(lastParams()).toMatchObject({ page: 2 }));
    const before = adminUsersList.mock.calls.length;
    pickRole("External client");
    await waitFor(() => expect(lastParams()).toMatchObject({ role: "external", page: 1 }));
    const filtered = adminUsersList.mock.calls.slice(before).map((c) => c[0]);
    expect(filtered).toEqual([expect.objectContaining({ role: "external", page: 1 })]);
  });

  it("opens the invite dialog and reloads after a created user", async () => {
    render(<AdminUsers me={admin} />);
    await screen.findByRole("button", { name: "Alice Smith" });
    fireEvent.click(screen.getByRole("button", { name: "Invite a user" }));
    fireEvent.click(screen.getByRole("button", { name: "invite-close" }));
    expect(screen.queryByTestId("invite")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Invite a user" }));
    const calls = adminUsersList.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "invite-created" }));
    await waitFor(() => expect(adminUsersList).toHaveBeenCalledTimes(calls + 1));
    expect(screen.queryByTestId("invite")).not.toBeInTheDocument();
  });

  it("opens user details, refreshes the picked row on change and closes on delete", async () => {
    adminUserGet.mockResolvedValue(user({ id: "u1", email: "alice@example.com", display_name: "Renamed" }));
    render(<AdminUsers me={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "Alice Smith" }));
    const detail = screen.getByTestId("detail");
    expect(within(detail).getByText("detail:alice@example.com:Alice Smith")).toBeInTheDocument();

    fireEvent.click(within(detail).getByRole("button", { name: "detail-changed" }));
    await waitFor(() => expect(adminUserGet).toHaveBeenCalledWith("u1"));
    expect(await screen.findByText("detail:alice@example.com:Renamed")).toBeInTheDocument();

    const calls = adminUsersList.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "detail-deleted" }));
    await waitFor(() => expect(adminUsersList).toHaveBeenCalledTimes(calls + 1));
    expect(screen.queryByTestId("detail")).not.toBeInTheDocument();
  });

  it("opens the card named by ?user= and drops the parameter on close", async () => {
    window.history.replaceState({}, "", "/admin/users?user=u9");
    adminUserGet.mockResolvedValue(user({ id: "u9", email: "linked@example.com", display_name: "Linked" }));
    render(<AdminUsers me={admin} />);
    expect(await screen.findByText("detail:linked@example.com:Linked")).toBeInTheDocument();
    expect(adminUserGet).toHaveBeenCalledWith("u9");
    fireEvent.click(screen.getByRole("button", { name: "detail-close" }));
    expect(screen.queryByTestId("detail")).not.toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("closes user details", async () => {
    render(<AdminUsers me={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: "ext@example.org" }));
    fireEvent.click(screen.getByRole("button", { name: "detail-close" }));
    expect(screen.queryByTestId("detail")).not.toBeInTheDocument();
  });
});
