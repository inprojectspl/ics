import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { AdminUser } from "../../api";
import { t, tn } from "../../lib/i18n";
import { UserDetailDialog } from "./UserDetailDialog";

const adminRevokeUserTokens = vi.fn();
const confirm = vi.fn();

vi.mock("../../api", () => ({
  api: { adminRevokeUserTokens: (...a: unknown[]) => adminRevokeUserTokens(...a) },
}));
vi.mock("../ConfirmDialog", () => ({ useConfirm: () => confirm }));

const user: AdminUser = {
  id: "u2",
  email: "bob@example.com",
  display_name: "Bob",
  role: "user",
  auth_method: "password",
  email_verified: true,
  email_verified_at: null,
  locked_until: null,
  locked: false,
  storage_quota_bytes: 1000,
  bundle_max_bytes: 100,
  html_autobypass: false,
  asset_count: 0,
  asset_bytes: 0,
  created_at: "2026-01-01T00:00:00Z",
  last_login_at: null,
};

beforeEach(() => {
  adminRevokeUserTokens.mockReset().mockResolvedValue({ revoked: 3 });
  confirm.mockReset().mockResolvedValue(true);
});

function open() {
  render(<UserDetailDialog user={user} onClose={vi.fn()} onChanged={vi.fn()} onDeleted={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: t("userDetail.revokeTokensAction") }));
}

describe("UserDetailDialog tokens", () => {
  it("revokes all tokens after confirmation and reports how many", async () => {
    open();
    await waitFor(() => expect(adminRevokeUserTokens).toHaveBeenCalledWith("u2"));
    expect(await screen.findByText(tn("userDetail.tokensRevoked", 3))).toBeInTheDocument();
  });

  it("does nothing when the admin cancels", async () => {
    confirm.mockResolvedValue(false);
    open();
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(adminRevokeUserTokens).not.toHaveBeenCalled();
  });
});

describe("UserDetailDialog sign-in method", () => {
  it("names a pending invitation and Google through the catalogue", () => {
    const { unmount } = render(
      <UserDetailDialog user={{ ...user, auth_method: "invite" }} onClose={vi.fn()} onChanged={vi.fn()} onDeleted={vi.fn()} />,
    );
    expect(screen.getByText(t("userDetail.signInInvite"))).toBeInTheDocument();
    unmount();
    render(<UserDetailDialog user={{ ...user, auth_method: "google_sso" }} onClose={vi.fn()} onChanged={vi.fn()} onDeleted={vi.fn()} />);
    expect(screen.getByText(t("adminUsers.authGoogle"))).toBeInTheDocument();
  });
});

describe("UserDetailDialog role", () => {
  it("names roles in words and explains the one picked", () => {
    render(<UserDetailDialog user={user} onClose={vi.fn()} onChanged={vi.fn()} onDeleted={vi.fn()} />);
    const select = screen.getByRole("combobox", { name: t("common.role") });
    expect([...(select as HTMLSelectElement).options].map((o) => o.textContent)).toEqual([
      t("common.roleUser"),
      t("common.roleExternal"),
      t("common.roleAdmin"),
    ]);
    expect(screen.getByText(t("userDetail.roleDescUser"))).toBeInTheDocument();
    const apply = screen.getAllByRole("button", { name: t("common.apply") })[0];
    expect(apply).toBeDisabled();
    fireEvent.change(select, { target: { value: "external" } });
    expect(screen.getByText(t("userDetail.roleDescExternal"))).toBeInTheDocument();
    expect(apply).toBeEnabled();
  });
});
