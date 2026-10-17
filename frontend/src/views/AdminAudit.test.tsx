import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { AuditEntry, Me } from "../api";
import { t } from "../lib/i18n";
import { AdminAudit, flattenByDay } from "./AdminAudit";

const listAudit = vi.fn();
const listAuditActions = vi.fn();

vi.mock("../api", () => ({
  api: {
    listAudit: (...a: unknown[]) => listAudit(...a),
    listAuditActions: (...a: unknown[]) => listAuditActions(...a),
  },
}));

const admin = { id: "u", email: "a@example.com", display_name: null, role: "admin" } as Me;

function entry(over: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: 1,
    timestamp: "2026-09-24T10:00:00Z",
    actor: "user:a@example.com",
    actor_label: null,
    actor_href: null,
    action: "asset_uploaded",
    target: null,
    target_label: null,
    target_href: null,
    payload: null,
    payload_refs: {},
    ip_hash: null,
    ...over,
  };
}

function entries(n: number): AuditEntry[] {
  return Array.from({ length: n }, (_, i) => entry({ id: n - i, actor: `user:${i}@example.com` }));
}

const rowButton = (name: string) => screen.getAllByRole("button", { name: new RegExp(name) })[0]!;

beforeEach(() => {
  // jsdom lacks scrollTo, which the virtualizer calls on mount.
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  listAudit.mockReset();
  listAuditActions.mockReset().mockResolvedValue(["asset_uploaded", "login_failed", "share_created"]);
});

describe("AdminAudit", () => {
  it("mounts only a window of rows for a long log", async () => {
    // jsdom has no layout; the virtualizer measures rows by offsetHeight.
    const height = vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(48);
    listAudit.mockResolvedValue({ items: entries(300), next_cursor: null });
    render(<AdminAudit me={admin} />);
    await waitFor(() => expect(screen.getAllByRole("listitem").length).toBeGreaterThan(0));
    expect(screen.getAllByRole("listitem").length).toBeLessThan(100);
    height.mockRestore();
  });

  it("aborts the previous request when a filter changes", async () => {
    const signals: AbortSignal[] = [];
    listAudit.mockImplementation((_params: unknown, signal: AbortSignal) => {
      signals.push(signal);
      return new Promise(() => {});
    });
    render(<AdminAudit me={admin} />);
    await waitFor(() => expect(signals.length).toBe(1));
    await screen.findByRole("option", { name: t("auditAction.login_failed") });
    fireEvent.change(screen.getByLabelText(t("adminAudit.action")), { target: { value: "login_failed" } });
    await waitFor(() => expect(signals.length).toBe(2));
    expect(signals[0]?.aborted).toBe(true);
    expect(signals[1]?.aborted).toBe(false);
  });
});

describe("flattenByDay", () => {
  it("puts one header before each day with its event count", () => {
    const rows = flattenByDay([
      entry({ id: 3, timestamp: "2026-09-24T10:00:00Z" }),
      entry({ id: 2, timestamp: "2026-09-24T09:00:00Z" }),
      entry({ id: 1, timestamp: "2026-09-20T09:00:00Z" }),
    ]);
    expect(rows.map((r) => r.kind)).toEqual(["day", "event", "event", "day", "event"]);
    expect(rows[0]).toMatchObject({ kind: "day", count: 2 });
    expect(rows[3]).toMatchObject({ kind: "day", count: 1 });
  });
});

describe("AdminAudit states and actions", () => {
  // jsdom has no layout; rows only mount once the virtualizer can measure them.
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(48);
  });

  function lastParams() {
    return listAudit.mock.calls.at(-1)?.[0] as Record<string, unknown>;
  }

  it("denies non-admins", () => {
    listAudit.mockResolvedValue({ items: [], next_cursor: null });
    render(<AdminAudit me={{ ...admin, role: "user" }} />);
    expect(screen.getByText(t("admin.noAccessTitle"))).toBeInTheDocument();
  });

  it("groups known actions by category under readable names", async () => {
    listAudit.mockResolvedValue({ items: [], next_cursor: null });
    render(<AdminAudit me={admin} />);
    await screen.findByRole("option", { name: t("auditAction.share_created") });
    const select = screen.getByLabelText(t("adminAudit.action"));
    const groups = [...select.querySelectorAll("optgroup")].map((g) => g.label);
    expect(groups).toEqual([
      t("adminAudit.category.account"),
      t("adminAudit.category.documents"),
      t("adminAudit.category.sharing"),
    ]);
  });

  it("shows the empty state and keeps working without known actions", async () => {
    listAuditActions.mockRejectedValue(new Error("nope"));
    listAudit.mockResolvedValue({ items: [], next_cursor: null });
    render(<AdminAudit me={admin} />);
    expect(await screen.findByText(t("adminAudit.emptyTitle"))).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: t("adminAudit.loadOlder") })).not.toBeInTheDocument();
  });

  it("shows the load error", async () => {
    listAudit.mockRejectedValue(new Error("audit exploded"));
    render(<AdminAudit me={admin} />);
    expect(await screen.findByText("audit exploded")).toBeInTheDocument();
  });

  it("names the event, the actor and the target in the row", async () => {
    listAudit.mockResolvedValue({
      items: [
        entry({ id: 3, action: "share_created", target: "share:s1", target_label: "Handbook" }),
        entry({ id: 2, action: "login_ok", target: "user:u1", target_label: "a@example.com" }),
        entry({ id: 1, action: "login_failed", actor: "anonymous" }),
      ],
      next_cursor: null,
    });
    render(<AdminAudit me={admin} />);
    const share = await screen.findByRole("button", { name: new RegExp(t("auditAction.share_created")) });
    expect(share).toHaveTextContent("a@example.com");
    expect(share).toHaveTextContent("Handbook");
    // A sign-in is about the actor; the name is said once.
    expect(rowButton(t("auditAction.login_ok"))).not.toHaveTextContent("→");
    // Refusals stand out.
    expect(within(rowButton(t("auditAction.login_failed"))).getByText(t("auditAction.login_failed"))).toHaveClass("text-danger");
  });

  it("falls back to the code for an action without a label", async () => {
    listAudit.mockResolvedValue({ items: [entry({ action: "brand_new_action" })], next_cursor: null });
    render(<AdminAudit me={admin} />);
    expect(await screen.findByRole("button", { name: /brand_new_action/ })).toBeInTheDocument();
  });

  it("opens an event with links, readable payload fields and its identifiers", async () => {
    listAudit.mockResolvedValue({
      items: [
        entry({
          id: 42,
          action: "asset_project_changed",
          actor: "user:a@example.com",
          actor_label: "a@example.com",
          actor_href: "/admin/users?user=u1",
          target: "asset:a1",
          target_label: "Contract",
          target_href: "/v/contract",
          payload: { to: "p1", from: null, has_password: false, tags: ["x", "y"], security: { status: "clean" } },
          payload_refs: { to: [{ label: "Legal", href: "/projects/legal" }] },
          ip_hash: "iphash1",
        }),
      ],
      next_cursor: null,
    });
    render(<AdminAudit me={admin} />);
    const row = await screen.findByRole("button", { name: new RegExp(t("auditAction.asset_project_changed")) });
    expect(row).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");

    expect(screen.getByRole("link", { name: "a@example.com" })).toHaveAttribute("href", "/admin/users?user=u1");
    expect(screen.getByRole("link", { name: "Contract" })).toHaveAttribute("href", "/v/contract");
    expect(screen.getByRole("link", { name: "Legal" })).toHaveAttribute("href", "/projects/legal");
    expect(screen.getByText(t("auditField.to"))).toBeInTheDocument();
    expect(screen.getByText(t("auditField.from")).nextSibling).toHaveTextContent(t("adminAudit.none"));
    expect(screen.getByText(t("auditField.has_password")).nextSibling).toHaveTextContent(t("common.no"));
    expect(screen.getByText("x, y")).toBeInTheDocument();
    expect(screen.getByText(/"status": "clean"/)).toBeInTheDocument();

    expect(screen.getByText(t("adminAudit.ids"))).toBeInTheDocument();
    expect(screen.getByText("asset:a1")).toBeInTheDocument();
    expect(screen.getByText("iphash1")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();

    fireEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(t("adminAudit.ids"))).not.toBeInTheDocument();
  });

  it("marks a named target that is gone as deleted, without a link", async () => {
    listAudit.mockResolvedValue({
      items: [entry({ action: "asset_deleted", target: "asset:a1", target_label: "Old" })],
      next_cursor: null,
    });
    render(<AdminAudit me={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: new RegExp(t("auditAction.asset_deleted")) }));
    expect(screen.queryByRole("link", { name: "Old" })).not.toBeInTheDocument();
    expect(screen.getByText(t("adminAudit.deleted"))).toBeInTheDocument();
  });

  it("loads older entries with the cursor and appends them", async () => {
    listAudit
      .mockResolvedValueOnce({ items: entries(2), next_cursor: 1 })
      .mockResolvedValueOnce({ items: [entry({ id: 100, actor: "user:older@example.com" })], next_cursor: null });
    render(<AdminAudit me={admin} />);
    fireEvent.click(await screen.findByRole("button", { name: t("adminAudit.loadOlder") }));
    await waitFor(() => expect(lastParams()).toMatchObject({ before_id: 1, limit: 50 }));
    expect(await screen.findByText("older@example.com")).toBeInTheDocument();
    expect(screen.getByText("0@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t("adminAudit.loadOlder") })).not.toBeInTheDocument();
  });

  it("debounces actor and target filters into the query", async () => {
    listAudit.mockResolvedValue({ items: [], next_cursor: null });
    render(<AdminAudit me={admin} />);
    await screen.findByText(t("adminAudit.emptyTitle"));
    fireEvent.change(screen.getByPlaceholderText(t("adminAudit.actorPlaceholder")), {
      target: { value: "user:a@example.com" },
    });
    fireEvent.change(screen.getByPlaceholderText(t("adminAudit.targetPlaceholder")), {
      target: { value: "asset:" },
    });
    await waitFor(() =>
      expect(lastParams()).toMatchObject({
        actor: "user:a@example.com",
        target: "asset:",
        before_id: undefined,
      }),
    );
  });
});
