import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ApiError } from "../../api/_core";
import { t } from "../../lib/i18n";
import { LinkTaskDialog } from "./LinkTaskDialog";

const addExternalRef = vi.fn();
const getOutline = vi.fn();

vi.mock("../../api", () => ({
  api: {
    addExternalRef: (...a: unknown[]) => addExternalRef(...a),
    getOutline: (...a: unknown[]) => getOutline(...a),
  },
}));

function renderDialog() {
  const onLinked = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <LinkTaskDialog assetId="a1" slug="manual" onClose={vi.fn()} onLinked={onLinked} />
    </QueryClientProvider>,
  );
  return { onLinked };
}

const change = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

beforeEach(() => {
  addExternalRef.mockReset().mockResolvedValue({});
  getOutline.mockReset().mockResolvedValue({ files: [{ path: "setup.md" }, { path: "faq.md" }] });
});

describe("LinkTaskDialog", () => {
  it("sends a work package link with every filled field", async () => {
    const { onLinked } = renderDialog();
    change(t("taskLinks.workPackage"), "4711");
    change(t("taskLinks.role"), "deliverable");
    fireEvent.click(screen.getByLabelText(t("taskLinks.requiredLabel")));
    await screen.findByLabelText(t("addRelation.file"));
    change(t("addRelation.file"), "setup.md");
    change(t("taskLinks.pinnedVersion"), "3");
    change(t("taskLinks.label"), "Module rollout");
    change(t("taskLinks.url"), "https://op.example.com/wp/4711");
    change(t("addRelation.note"), "section 2");
    fireEvent.click(screen.getByRole("button", { name: t("taskLinks.link") }));

    await waitFor(() => expect(onLinked).toHaveBeenCalled());
    expect(addExternalRef).toHaveBeenCalledWith("a1", {
      system: "openproject",
      entity: "work_package",
      external_id: "4711",
      role: "deliverable",
      required: true,
      asset_path: "setup.md",
      pinned_version: 3,
      label: "Module rollout",
      url: "https://op.example.com/wp/4711",
      note: "section 2",
    });
  });

  it("sends a PS node with its project scope", async () => {
    renderDialog();
    change(t("taskLinks.kind"), "node");
    change(t("taskLinks.node"), "n-8f2c");
    expect(screen.getByRole("button", { name: t("taskLinks.link") })).toBeDisabled();
    change(t("taskLinks.scope"), "demo");
    fireEvent.click(screen.getByRole("button", { name: t("taskLinks.link") }));
    await waitFor(() =>
      expect(addExternalRef).toHaveBeenCalledWith("a1", {
        system: "project_standard",
        entity: "node",
        external_id: "n-8f2c",
        external_scope: "demo",
        role: "context",
        required: false,
      }),
    );
  });

  it("rejects a malformed work package number before sending", () => {
    renderDialog();
    change(t("taskLinks.workPackage"), "WP-12");
    expect(screen.getByText(t("taskLinks.workPackageInvalid"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("taskLinks.link") })).toBeDisabled();
  });

  it("shows the catalogue message for external_ref_exists", async () => {
    addExternalRef.mockRejectedValue(new ApiError(409, "exists", "exists", "external_ref_exists"));
    const { onLinked } = renderDialog();
    change(t("taskLinks.workPackage"), "4711");
    fireEvent.click(screen.getByRole("button", { name: t("taskLinks.link") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("error.external_ref_exists"));
    expect(onLinked).not.toHaveBeenCalled();
  });
});
