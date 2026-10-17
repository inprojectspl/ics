import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { AccessToken, Me } from "../api";
import { t } from "../lib/i18n";
import { AccessTokens, dayOffset } from "./AccessTokens";
import { AccessTokensLazy } from "./accessTokensLazy";
import { renderWithClient } from "../test-utils";

const listTokens = vi.fn();
const createToken = vi.fn();
const revokeToken = vi.fn();
const confirm = vi.fn();

vi.mock("../api", () => ({
  api: {
    listTokens: (...a: unknown[]) => listTokens(...a),
    createToken: (...a: unknown[]) => createToken(...a),
    revokeToken: (...a: unknown[]) => revokeToken(...a),
  },
}));
vi.mock("../components/ViewerChrome", () => ({ ViewerChrome: () => null }));
vi.mock("../components/ConfirmDialog", () => ({ useConfirm: () => confirm }));

const me = { id: "u1", email: "a@example.com", display_name: null, role: "user" } as Me;
const SECRET = "ics_pat_ab12cd34_s3cr3t-value-that-must-not-leak";

const existing: AccessToken = {
  id: "t1",
  name: "laptop",
  prefix: "0f0f0f0f",
  scopes: ["ics:read"],
  expires_at: "2026-12-01T00:00:00Z",
  last_used_at: null,
  created_at: "2026-09-01T00:00:00Z",
};
const fresh: AccessToken = { ...existing, id: "t2", name: "ci", prefix: "ab12cd34" };

beforeEach(() => {
  listTokens.mockReset().mockResolvedValue({ items: [existing] });
  createToken.mockReset().mockResolvedValue({ ...fresh, token: SECRET });
  revokeToken.mockReset().mockResolvedValue(undefined);
  confirm.mockReset().mockResolvedValue(true);
});

async function create(name: string) {
  fireEvent.change(screen.getByLabelText(t("accessTokens.nameLabel")), { target: { value: name } });
  fireEvent.click(screen.getByRole("button", { name: t("accessTokens.create") }));
}

describe("AccessTokens", () => {
  it("loads lazily", async () => {
    renderWithClient(
      <Suspense fallback={<p>lazy-fallback</p>}>
        <AccessTokensLazy me={me} />
      </Suspense>,
    );
    expect(screen.getByText("lazy-fallback")).toBeInTheDocument();
    expect(await screen.findByText("laptop")).toBeInTheDocument();
  });

  it("lists tokens by prefix only", async () => {
    renderWithClient(<AccessTokens me={me} />);
    const list = within(await screen.findByRole("list", { name: t("accessTokens.listLabel") }));
    expect(list.getByText("ics_pat_0f0f0f0f_…")).toBeInTheDocument();
    expect(list.getByText(t("accessTokens.neverUsed"), { exact: false })).toBeInTheDocument();
  });

  it("shows the full token only right after creation", async () => {
    listTokens
      .mockResolvedValueOnce({ items: [existing] })
      .mockResolvedValue({ items: [existing, fresh] });
    renderWithClient(<AccessTokens me={me} />);
    await screen.findByText("laptop");
    await create("ci");

    expect(await screen.findByText(SECRET)).toBeInTheDocument();
    expect(createToken).toHaveBeenCalledWith("ci", `${dayOffset(90)}T00:00:00Z`);
    const list = within(await screen.findByRole("list", { name: t("accessTokens.listLabel") }));
    await waitFor(() => expect(list.getByText("ics_pat_ab12cd34_…")).toBeInTheDocument());
    expect(list.queryByText(SECRET)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: t("accessTokens.done") }));
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });

  it("does not show the secret after a reload of the page", async () => {
    listTokens.mockResolvedValue({ items: [existing, fresh] });
    renderWithClient(<AccessTokens me={me} />);
    await screen.findByText("ci");
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("s3cr3t");
  });

  it("revokes a token after confirmation", async () => {
    renderWithClient(<AccessTokens me={me} />);
    await screen.findByText("laptop");
    listTokens.mockResolvedValue({ items: [] });
    fireEvent.click(screen.getByRole("button", { name: t("accessTokens.revoke") }));
    expect(await screen.findByText(t("accessTokens.empty"))).toBeInTheDocument();
    expect(revokeToken).toHaveBeenCalledWith("t1");
  });

  it("keeps the expiry within 180 days", () => {
    const now = new Date("2026-09-26T12:00:00Z");
    expect(dayOffset(1, now)).toBe("2026-09-27");
    expect(dayOffset(180, now)).toBe("2027-03-25");
  });
});
