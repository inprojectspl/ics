import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { Me, ReviewItem } from "../api";
import { ApiError } from "../api/_core";
import { ToastProvider } from "../components/Toast";
import { t, tn } from "../lib/i18n";
import { AdminReview } from "./AdminReview";

const adminReviewQueue = vi.fn();
const adminGrantBypass = vi.fn();

vi.mock("../api", () => ({
  api: {
    adminReviewQueue: (...a: unknown[]) => adminReviewQueue(...a),
    adminGrantBypass: (...a: unknown[]) => adminGrantBypass(...a),
  },
}));

const admin = { id: "u", email: "a@example.com", display_name: null, role: "admin" } as Me;

function item(over: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: "a1",
    slug: "dash-board",
    title: "Dashboard",
    kind: "html_bundle",
    owner_id: "o1",
    owner_email: "owner@example.com",
    version: 2,
    size_bytes: 2048,
    security_status: "critical",
    security_report: {
      status: "critical",
      findings: [
        { severity: "critical", rule: "eval_call", file: "dist/index.html", line: 3, message: "eval()" },
        { severity: "warn", rule: "inline_handler", file: "dist/app/main.js", line: null, message: "inline handler" },
        { severity: "info", rule: "meta_refresh", file: "dist/a.html", line: 1, message: "meta refresh" },
        { severity: "info", rule: "meta_refresh", file: "dist/b.html", line: 1, message: "meta refresh" },
      ],
    },
    security_bypass: false,
    security_bypass_at: null,
    security_bypass_by: null,
    security_bypass_reason: null,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
    ...over,
  };
}

function renderReview(me: Me = admin) {
  return render(
    <ToastProvider>
      <AdminReview me={me} />
    </ToastProvider>,
  );
}

const expand = async (title = "Dashboard") => {
  const row = await screen.findByRole("button", { name: new RegExp(title) });
  fireEvent.click(row);
  return row;
};
const grantButton = () => screen.getByRole("button", { name: t("adminReview.grant") });
const reason = () => screen.getByLabelText(t("adminReview.reasonLabel"));

beforeEach(() => {
  adminReviewQueue.mockReset();
  adminGrantBypass.mockReset().mockResolvedValue(item({ security_bypass: true }));
});

describe("AdminReview", () => {
  it("denies non-admins without fetching", () => {
    renderReview({ ...admin, role: "user" });
    expect(screen.getByText(t("admin.noAccessTitle"))).toBeInTheDocument();
    expect(adminReviewQueue).not.toHaveBeenCalled();
  });

  it("shows the empty queue", async () => {
    adminReviewQueue.mockResolvedValue([]);
    renderReview();
    expect(await screen.findByText(t("adminReview.emptyTitle"))).toBeInTheDocument();
  });

  it("shows the load error instead of the empty state", async () => {
    adminReviewQueue.mockRejectedValue(new ApiError(500, "queue down", "queue down", "server_error"));
    renderReview();
    expect(await screen.findByText("Server error. Try again.")).toBeInTheDocument();
    expect(screen.queryByText(t("adminReview.emptyTitle"))).not.toBeInTheDocument();
  });

  it("lists bundles with their owner and counts per severity", async () => {
    adminReviewQueue.mockResolvedValue([item(), item({ id: "a2", slug: "no-title", title: null, security_report: null })]);
    renderReview();
    const row = await screen.findByRole("button", { name: /Dashboard/ });
    expect(screen.getByText(tn("adminReview.pending", 2))).toBeInTheDocument();
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(row).toHaveTextContent("owner@example.com");
    expect(within(row).getByText(tn("adminReview.criticalCount", 1))).toBeInTheDocument();
    expect(within(row).getByText(tn("adminReview.warnCount", 1))).toBeInTheDocument();
    expect(within(row).getByText(tn("adminReview.infoCount", 2))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /no-title/ })).toBeInTheDocument();
  });

  it("opens in place with every finding grouped by rule and full paths", async () => {
    adminReviewQueue.mockResolvedValue([item()]);
    renderReview();
    const row = await expand();
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // The shared folder is said once; paths are relative to it.
    expect(screen.getByText("dist/")).toBeInTheDocument();
    expect(screen.getByText("app/main.js", { exact: false })).toBeInTheDocument();
    const refresh = screen.getByRole("heading", { name: "meta refresh" }).closest("section")!;
    expect(within(refresh).getByText(tn("securityFindings.places", 2))).toBeInTheDocument();
    expect(within(refresh).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("link", { name: t("adminReview.openDocument") })).toHaveAttribute("href", "/v/dash-board");

    fireEvent.click(row);
    expect(screen.queryByLabelText(t("adminReview.reasonLabel"))).not.toBeInTheDocument();
  });

  it("keeps approval disabled until the reason is long enough", async () => {
    adminReviewQueue.mockResolvedValue([item()]);
    renderReview();
    await expand();
    expect(grantButton()).toBeDisabled();
    fireEvent.change(reason(), { target: { value: "  short  " } });
    expect(grantButton()).toBeDisabled();
    fireEvent.change(reason(), { target: { value: "confirmed" } });
    expect(grantButton()).toBeEnabled();
    expect(adminGrantBypass).not.toHaveBeenCalled();
  });

  it("approves with the trimmed reason, confirms it and reloads the queue", async () => {
    adminReviewQueue.mockResolvedValueOnce([item()]).mockResolvedValueOnce([]);
    renderReview();
    await expand();
    fireEvent.change(reason(), { target: { value: "  confirmed with the owner  " } });
    fireEvent.click(grantButton());
    await waitFor(() => expect(adminGrantBypass).toHaveBeenCalledWith("a1", "confirmed with the owner"));
    expect(await screen.findByText(t("adminReview.granted", { title: "Dashboard" }))).toBeInTheDocument();
    expect(await screen.findByText(t("adminReview.emptyTitle"))).toBeInTheDocument();
    expect(adminReviewQueue).toHaveBeenCalledTimes(2);
  });

  it("keeps the form open with the error when approving fails", async () => {
    adminReviewQueue.mockResolvedValue([item()]);
    adminGrantBypass.mockRejectedValue(
      new ApiError(409, "bypass already granted", "bypass already granted", "bypass_already_granted"),
    );
    renderReview();
    await expand();
    fireEvent.change(reason(), { target: { value: "long enough reason" } });
    fireEvent.click(grantButton());
    expect(await screen.findByText("The exception has already been granted.")).toBeInTheDocument();
    expect(grantButton()).toBeEnabled();
    expect(reason()).toHaveValue("long enough reason");
  });
});
