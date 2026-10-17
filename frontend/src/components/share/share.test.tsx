import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { AssetSummary, ShareLink } from "../../api";
import { api } from "../../api";
import { t } from "../../lib/i18n";
import { renderWithClient } from "../../test-utils";
import { mockMedia } from "../../test-media";
import { ConfirmProvider } from "../ConfirmDialog";
import { ShareDialog } from "../ShareDialog";
import { ToastProvider } from "../Toast";
import { NewLinkForm } from "./NewLinkForm";

const esc = (s: string) => new RegExp(s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));

const asset: AssetSummary = {
  id: "a1",
  slug: "s1",
  title: "Plan",
  kind: "md_single",
  size_bytes: 1,
  version: 1,
  security_status: "clean",
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};

const link = (over: Partial<ShareLink> = {}): ShareLink => ({
  id: "l1",
  token: "tok",
  mode: "public",
  url: "https://ics.example/s/tok",
  expires_at: null,
  max_views: null,
  view_count: 4,
  revoked_at: null,
  created_at: "2026-09-01T00:00:00Z",
  allowed_emails: null,
  requires_password: false,
  ...over,
});

beforeEach(() => mockMedia({ width: 1440 }));

describe("NewLinkForm", () => {
  it("a magic link needs addresses", async () => {
    const onCreate = vi.fn();
    const onInvalid = vi.fn();
    render(<NewLinkForm busy={false} error={null} onCreate={onCreate} onInvalid={onInvalid} />);
    fireEvent.click(screen.getByRole("radio", { name: esc(t("shareDialog.modeMagicEmail")) }));
    fireEvent.click(screen.getByRole("button", { name: t("shareDialog.createLink") }));
    expect(onInvalid).toHaveBeenCalledWith(t("shareDialog.emailsRequired"));
    expect(onCreate).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: t("shareDialog.emailsLabel") }), { target: { value: "a@x.pl, b@y.pl;c@z.pl" } });
    fireEvent.click(screen.getByRole("button", { name: t("shareDialog.createLink") }));
    await waitFor(() => expect(onCreate).toHaveBeenCalled());
    expect(onCreate.mock.calls[0]?.[0]).toMatchObject({ mode: "magic_email", allowed_emails: ["a@x.pl", "b@y.pl", "c@z.pl"], max_views: null });
  });

  it("sends a password link with limits and resets after success", async () => {
    const onCreate = vi.fn().mockResolvedValue(true);
    render(<NewLinkForm busy={false} error="Error" onCreate={onCreate} onInvalid={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Error");
    const pwd = screen.getByRole("textbox", { name: t("shareDialog.passwordLabel") });
    fireEvent.change(pwd, { target: { value: "sekretne-haslo" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: t("shareDialog.ttlLabel") }), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("checkbox", { name: esc(t("shareDialog.oneTime")) }));
    fireEvent.click(screen.getByRole("button", { name: t("shareDialog.createLink") }));
    await waitFor(() => expect(onCreate).toHaveBeenCalled());
    const sent = onCreate.mock.calls[0]?.[0];
    expect(sent).toMatchObject({ mode: "password", password: "sekretne-haslo", max_views: 1 });
    expect(sent.expires_at).not.toBeNull();
    await waitFor(() => expect(pwd).toHaveValue(""));
  });

  it("keeps the input when the creation failed", async () => {
    render(<NewLinkForm busy={false} error={null} onCreate={vi.fn().mockResolvedValue(false)} onInvalid={vi.fn()} />);
    fireEvent.click(screen.getByRole("radio", { name: esc(t("shareDialog.modePublic")) }));
    fireEvent.change(screen.getByRole("spinbutton", { name: t("shareDialog.ttlLabel") }), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: t("shareDialog.createLink") }));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.getByRole("spinbutton", { name: t("shareDialog.ttlLabel") })).toHaveValue(3);
  });
});

function renderDialog() {
  return renderWithClient(
    <ToastProvider>
      <ConfirmProvider>
        <ShareDialog asset={asset} onClose={vi.fn()} />
      </ConfirmProvider>
    </ToastProvider>,
  );
}

describe("ShareDialog", () => {
  it("links first: copy and revoke, a new one in the disclosure", async () => {
    vi.spyOn(api, "listShares").mockResolvedValue([link(), link({ id: "l2", url: "https://ics.example/s/old", revoked_at: "2026-09-02T00:00:00Z" })]);
    vi.spyOn(api, "listAssetShares").mockResolvedValue([]);
    vi.spyOn(api, "listProjectShares").mockResolvedValue([]);
    vi.spyOn(api, "listProjects").mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 } as Awaited<ReturnType<typeof api.listProjects>>);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const revoke = vi.spyOn(api, "revokeShare").mockResolvedValue(undefined as never);
    renderDialog();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((x) => x.textContent)).toEqual([`${t("shareDialog.tabLinks")} (1)`, t("shareDialog.tabPeople"), t("shareDialog.tabProjects")]);
    const list = await screen.findByRole("list", { name: t("shareDialog.activeLinks") });
    expect(within(list).getByText("https://ics.example/s/tok")).toBeInTheDocument();
    expect(within(list).getByText(t("shareDialog.revoked"))).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: t("secretReveal.copy") }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("https://ics.example/s/tok"));
    fireEvent.click(within(list).getByRole("button", { name: t("shareDialog.revokeLinkConfirm") }));
    const confirm = await screen.findByRole("dialog", { name: t("shareDialog.revokeLinkTitle") });
    fireEvent.click(within(confirm).getByRole("button", { name: t("shareDialog.revokeLinkConfirm") }));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("l1"));
    expect(screen.getByRole("button", { name: t("shareDialog.newLink") })).toHaveAttribute("aria-expanded", "false");
  });

  it("people: add by e-mail with a role and revoke", async () => {
    vi.spyOn(api, "listShares").mockResolvedValue([]);
    vi.spyOn(api, "listAssetShares").mockResolvedValue([
      { id: "r1", user_id: "u2", email: "b@x.pl", display_name: "Bob", role: "editor", granted_at: "2026-09-01T00:00:00Z", granted_by: null },
    ]);
    const add = vi.spyOn(api, "createAssetShare").mockResolvedValue({ email: "c@x.pl", new_account: false } as Awaited<ReturnType<typeof api.createAssetShare>>);
    renderDialog();
    expect(await screen.findByText(t("shareDialog.noLinks"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Osoby|People/ }));
    expect(await screen.findByText("Bob")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: t("shareDialog.emailLabel") }), { target: { value: "c@x.pl" } });
    fireEvent.change(screen.getByRole("combobox", { name: t("common.role") }), { target: { value: "editor" } });
    fireEvent.click(screen.getByRole("button", { name: t("common.add") }));
    await waitFor(() => expect(add).toHaveBeenCalledWith("s1", "c@x.pl", "editor"));
  });

  it("with no rights at all it says so once", async () => {
    const forbidden = Object.assign(new Error("x"), { status: 403 });
    vi.spyOn(api, "listShares").mockRejectedValue(forbidden);
    vi.spyOn(api, "listAssetShares").mockRejectedValue(forbidden);
    renderDialog();
    await waitFor(() => expect(api.listAssetShares).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    await waitFor(() => expect(screen.queryByRole("tab")).not.toBeInTheDocument());
  });
});
