import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { AssetSummary } from "../../api";
import { t } from "../../lib/i18n";
import { renderWithClient } from "../../test-utils";
import { BindingDialog } from "./BindingDialog";

const createBinding = vi.fn();

vi.mock("../../api", () => ({
  api: {
    listBindings: vi.fn(async () => []),
    listNotificationProviders: vi.fn(async () => [
      { id: "google_chat", display_name: "Google Chat", url_hint: "https://chat.googleapis.com/…" },
    ]),
    createBinding: (...a: unknown[]) => createBinding(...a),
    authConfig: vi.fn(async () => ({})),
  },
}));
vi.mock("../ConfirmDialog", () => ({ useConfirm: () => vi.fn() }));

const asset = { id: "a1", slug: "doc", title: "Doc", kind: "md_collection" } as AssetSummary;

beforeEach(() => {
  createBinding.mockReset().mockReturnValue(new Promise(() => {}));
});

describe("BindingDialog notification provider", () => {
  it("keeps No notification once picked instead of snapping back to the first provider", async () => {
    renderWithClient(<BindingDialog asset={asset} onClose={vi.fn()} />);
    const select = screen.getByRole("combobox");
    await waitFor(() => expect(select).toHaveValue("google_chat"));

    fireEvent.change(select, { target: { value: "" } });
    expect(select).toHaveValue("");

    fireEvent.click(screen.getByRole("button", { name: t("bindingDialog.create") }));
    await waitFor(() => expect(createBinding).toHaveBeenCalled());
    expect(createBinding.mock.calls[0]?.[1]).toEqual({ gitlabUrl: undefined, webhook: undefined });
  });
});
