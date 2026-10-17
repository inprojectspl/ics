import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { ExternalRef } from "../../api";
import { ApiError } from "../../api/_core";
import { t } from "../../lib/i18n";
import { TaskLinks } from "./TaskLinks";
import { refNumber, safeUrl } from "./taskRef";

const listExternalRefs = vi.fn();
const deleteExternalRef = vi.fn();

vi.mock("../../api", () => ({
  api: {
    listExternalRefs: (...a: unknown[]) => listExternalRefs(...a),
    deleteExternalRef: (...a: unknown[]) => deleteExternalRef(...a),
    getOutline: () => Promise.resolve({}),
  },
}));

function ref(over: Partial<ExternalRef> = {}): ExternalRef {
  return {
    id: "x1",
    asset_id: "a1",
    system: "openproject",
    entity: "work_package",
    external_id: "4711",
    external_scope: null,
    role: "context",
    required: false,
    label: null,
    url: null,
    asset_path: null,
    pinned_version: null,
    basis_changed: false,
    note: null,
    origin: "manual",
    created_at: null,
    ...over,
  };
}

const HTML_LABEL = '<img src=x onerror="alert(1)"><b>Rollout</b>';

function renderLinks(canEdit: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TaskLinks assetId="a1" slug="spec" canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  listExternalRefs.mockReset().mockResolvedValue([
    ref({ label: HTML_LABEL, url: "https://op.example.com/wp/4711", required: true, role: "deliverable" }),
    ref({ id: "x2", system: "project_standard", entity: "node", external_id: "n-8f2c", external_scope: "demo", url: "javascript:alert(1)" }),
  ]);
  deleteExternalRef.mockReset().mockResolvedValue({ deleted: true });
});

describe("TaskLinks", () => {
  it("renders an HTML label as plain text", async () => {
    const { container } = renderLinks(false);
    expect(await screen.findByText(HTML_LABEL)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("shows number, link, required and deliverable badges; unsafe links stay text", async () => {
    renderLinks(false);
    expect(await screen.findByText(t("taskLinks.title"))).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "#4711" });
    expect(link).toHaveAttribute("href", "https://op.example.com/wp/4711");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(t("taskLinks.required"))).toBeInTheDocument();
    expect(screen.getByText(t("taskLinks.roleDeliverable"))).toBeInTheDocument();
    expect(screen.getByText("demo/n-8f2c")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "demo/n-8f2c" })).not.toBeInTheDocument();
  });

  it("gives editors remove and link actions, readers none", async () => {
    const { unmount } = renderLinks(false);
    await screen.findByText("demo/n-8f2c");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    unmount();

    renderLinks(true);
    fireEvent.click(await screen.findByRole("button", { name: t("taskLinks.removeLabel", { task: "#4711" }) }));
    await waitFor(() => expect(deleteExternalRef).toHaveBeenCalledWith("x1"));
    await waitFor(() => expect(screen.queryByText("#4711")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: t("taskLinks.link") })).toBeInTheDocument();
  });

  it("disappears without graph access", async () => {
    listExternalRefs.mockRejectedValue(new ApiError(404, "nf", "nf", "asset_not_found"));
    const { container } = renderLinks(true);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});

describe("taskRef", () => {
  it("formats numbers and keeps only http(s) links", () => {
    expect(refNumber(ref())).toBe("#4711");
    expect(refNumber(ref({ system: "project_standard", entity: "node", external_id: "n-1", external_scope: "p" }))).toBe("p/n-1");
    expect(safeUrl("https://x.io/a")).toBe("https://x.io/a");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("not a url")).toBeNull();
  });
});
