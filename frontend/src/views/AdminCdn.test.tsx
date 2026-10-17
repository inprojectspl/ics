import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { Me } from "../api";
import { ApiError } from "../api/_core";
import { t } from "../lib/i18n";
import { AdminCdn } from "./AdminCdn";

const adminCdnList = vi.fn();
const adminCdnAdd = vi.fn();
const adminCdnRemove = vi.fn();
const confirm = vi.fn();

vi.mock("../api", () => ({
  api: {
    adminCdnList: (...a: unknown[]) => adminCdnList(...a),
    adminCdnAdd: (...a: unknown[]) => adminCdnAdd(...a),
    adminCdnRemove: (...a: unknown[]) => adminCdnRemove(...a),
  },
}));
vi.mock("../components/ConfirmDialog", () => ({ useConfirm: () => confirm }));

const admin = { id: "u", email: "a@example.com", display_name: null, role: "admin" } as Me;

const listing = {
  builtin: ["cdn.jsdelivr.net", "cdnjs.cloudflare.com"],
  runtime: [
    {
      id: "r1",
      host: "cdn.example.com",
      note: "internal assets",
      added_by: "a@example.com",
      created_at: "2026-09-01T10:00:00Z",
    },
    { id: "r2", host: "static.example.org", note: null, added_by: null, created_at: "2026-09-02T10:00:00Z" },
  ],
};

beforeEach(() => {
  adminCdnList.mockReset().mockResolvedValue(listing);
  adminCdnAdd.mockReset().mockResolvedValue({ id: "r3", host: "x" });
  adminCdnRemove.mockReset().mockResolvedValue(undefined);
  confirm.mockReset().mockResolvedValue(true);
});

const host = () => screen.getByLabelText(t("adminCdn.hostLabel"));
const note = () => screen.getByLabelText(t("adminCdn.noteLabel"));
const removeButton = (h: string) => screen.getByRole("button", { name: t("adminCdn.removeHost", { host: h }) });

async function openAddDialog() {
  render(<AdminCdn me={admin} />);
  await screen.findByText("cdn.example.com");
  fireEvent.click(screen.getByRole("button", { name: t("adminCdn.addHost") }));
  return screen.getByRole("dialog", { name: t("adminCdn.addHost") });
}

describe("AdminCdn", () => {
  it("denies non-admins without fetching", () => {
    render(<AdminCdn me={{ ...admin, role: "user" }} />);
    expect(screen.getByText("No access")).toBeInTheDocument();
    expect(adminCdnList).not.toHaveBeenCalled();
  });

  it("lists runtime hosts with their note and keeps built-in hosts folded", async () => {
    render(<AdminCdn me={admin} />);
    expect(await screen.findByText("cdn.example.com")).toBeInTheDocument();
    expect(screen.getByText(/internal assets/)).toBeInTheDocument();
    expect(removeButton("cdn.example.com")).toBeInTheDocument();
    expect(removeButton("static.example.org")).toBeInTheDocument();

    const builtin = screen.getByRole("button", { name: t("adminCdn.builtin") });
    expect(builtin).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("cdn.jsdelivr.net")).not.toBeVisible();
    fireEvent.click(builtin);
    expect(screen.getByText("cdn.jsdelivr.net")).toBeVisible();
    expect(screen.queryByRole("button", { name: t("adminCdn.removeHost", { host: "cdn.jsdelivr.net" }) })).toBeNull();
  });

  it("shows a short empty state and keeps adding to the header button", async () => {
    adminCdnList.mockResolvedValue({ builtin: [], runtime: [] });
    render(<AdminCdn me={admin} />);
    expect(await screen.findByText(t("adminCdn.runtimeEmptyTitle"))).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: t("adminCdn.addHost") })).toHaveLength(1);
  });

  it("shows the load error", async () => {
    adminCdnList.mockRejectedValue(new ApiError(500, "boom", "boom", "server_error"));
    render(<AdminCdn me={admin} />);
    expect(await screen.findByText("Server error. Try again.")).toBeInTheDocument();
  });

  it("adds a normalised host with its note, closes the dialog and reloads", async () => {
    const dialog = await openAddDialog();
    const submit = within(dialog).getByRole("button", { name: t("adminCdn.submit") });
    expect(submit).toBeDisabled();
    fireEvent.change(host(), { target: { value: "  CDN.Acme.io " } });
    fireEvent.change(note(), { target: { value: " vendor " } });
    fireEvent.click(submit);
    await waitFor(() => expect(adminCdnAdd).toHaveBeenCalledWith("cdn.acme.io", "vendor"));
    await waitFor(() => expect(adminCdnList).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("passes no note when it is blank and keeps the dialog open on an add error", async () => {
    adminCdnAdd.mockRejectedValue(new ApiError(400, "invalid host", "invalid host", "invalid_cdn_host"));
    const dialog = await openAddDialog();
    fireEvent.change(host(), { target: { value: "bad host" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("adminCdn.submit") }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/Invalid host/);
    expect(adminCdnAdd).toHaveBeenCalledWith("bad host", undefined);
    expect(host()).toHaveValue("bad host");
  });

  it("shows the message chosen by the error code", async () => {
    adminCdnAdd.mockRejectedValue(
      new ApiError(409, "duplicate host cdn.acme.io", "duplicate host cdn.acme.io", "cdn_host_exists"),
    );
    const dialog = await openAddDialog();
    fireEvent.change(host(), { target: { value: "cdn.acme.io" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("adminCdn.submit") }));
    expect(await screen.findByText("This host is already on the list.")).toBeInTheDocument();
    expect(screen.queryByText(/duplicate host/)).not.toBeInTheDocument();
  });

  it("cancels the dialog without adding", async () => {
    const dialog = await openAddDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: t("common.cancel") }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(adminCdnAdd).not.toHaveBeenCalled();
  });

  it("removes a host after confirmation", async () => {
    render(<AdminCdn me={admin} />);
    await screen.findByText("cdn.example.com");
    fireEvent.click(removeButton("cdn.example.com"));
    await waitFor(() => expect(adminCdnRemove).toHaveBeenCalledWith("r1"));
    expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ destructive: true }));
    await waitFor(() => expect(adminCdnList).toHaveBeenCalledTimes(2));
  });

  it("keeps the host when the confirm is cancelled", async () => {
    confirm.mockResolvedValue(false);
    render(<AdminCdn me={admin} />);
    await screen.findByText("cdn.example.com");
    fireEvent.click(removeButton("static.example.org"));
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(adminCdnRemove).not.toHaveBeenCalled();
  });

  it("shows a remove error", async () => {
    adminCdnRemove.mockRejectedValue(new ApiError(404, "CDN host not found", "CDN host not found", "cdn_host_not_found"));
    render(<AdminCdn me={admin} />);
    await screen.findByText("cdn.example.com");
    fireEvent.click(removeButton("cdn.example.com"));
    expect(await screen.findByText("Host not found on the list.")).toBeInTheDocument();
  });
});
