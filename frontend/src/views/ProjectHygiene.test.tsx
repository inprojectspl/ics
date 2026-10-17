import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { HygieneItem, HygieneList, Me, ProjectHygiene as Hygiene } from "../api";
import { ApiError } from "../api/_core";
import { ProjectTabs } from "../components/ProjectTabs";
import { t } from "../lib/i18n";
import { ProjectHygieneLazy } from "./hygiene/lazy";
import { ProjectHygiene } from "./ProjectHygiene";
import { renderWithClient } from "../test-utils";

const api = vi.hoisted(() => ({
  getProjectHygiene: vi.fn(),
  patchMeta: vi.fn(),
  markReviewed: vi.fn(),
  getAssetMeta: vi.fn(),
  listRelations: vi.fn(),
  patchRelation: vi.fn(),
  listExternalRefs: vi.fn(),
  addExternalRef: vi.fn(),
  deleteExternalRef: vi.fn(),
  markDuplicate: vi.fn(),
  dismissDuplicate: vi.fn(),
  listProjects: vi.fn(),
}));
const toast = vi.fn();
const confirm = vi.fn();

vi.mock("../api", () => ({ api }));
vi.mock("../components/Toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("../components/ConfirmDialog", () => ({ useConfirm: () => confirm }));
vi.mock("../lib/useDocTypes", () => ({
  useDocTypes: () => [{ key: "design", label: "Design", archived: false, archived_at: null }],
  useDocTypeLabels: () => new Map(),
}));

const me = { id: "u1", email: "a@example.com", display_name: null, role: "user" } as Me;

const item: HygieneItem = {
  id: "a1",
  slug: "doc1",
  title: "Architecture",
  kind: "md_single",
  doc_type: null,
  version: 3,
  summary_version: null,
  review_due_at: null,
  content_updated_at: null,
};

function response(list: HygieneList, count: number, over: Partial<Hygiene> = {}): Hygiene {
  return {
    project: { id: "p", slug: "p1", name: "Apollo" },
    counters: {
      no_summary: 0,
      summary_stale: 0,
      no_doc_type: 0,
      review_overdue: 0,
      basis_changed: 0,
      superseded_linked: 0,
      hidden_edges: 0,
      [list]: count,
    },
    list,
    page: 1,
    page_size: 25,
    total: count,
    items: count > 0 ? [item] : [],
    ...over,
  };
}

function open(list: HygieneList) {
  window.history.replaceState({}, "", `/projects/p1/hygiene?list=${list}`);
  renderWithClient(<ProjectHygiene me={me} slug="p1" />);
}

/** Count shown next to a list in the list switcher. */
function counter(label: string) {
  const lists = screen.getByRole("navigation", { name: t("hygiene.lists") });
  return within(lists).getByRole("button", { name: new RegExp(label) });
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.listProjects.mockResolvedValue({
    items: [{ id: "p", slug: "p1", name: "Apollo", description: null, created_by: "u1", created_at: "2026-01-01T00:00:00Z", my_role: "owner", member_count: 1, asset_count: 1 }],
    total: 1,
    page: 1,
    page_size: 200,
  });
  toast.mockReset();
  confirm.mockReset().mockResolvedValue(true);
});
afterEach(() => window.history.replaceState({}, "", "/"));

describe("ProjectHygiene", () => {
  it("loads lazily", async () => {
    api.getProjectHygiene.mockResolvedValue(response("no_summary", 0));
    renderWithClient(
      <Suspense fallback={<p>lazy-fallback</p>}>
        <ProjectHygieneLazy me={me} slug="p1" />
      </Suspense>,
    );
    expect(screen.getByText("lazy-fallback")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Apollo" })).toBeInTheDocument();
    expect(await screen.findByText(t("hygiene.empty"))).toBeInTheDocument();
  });

  it("sets a doc type from the row and refreshes the counter", async () => {
    api.getProjectHygiene
      .mockResolvedValueOnce(response("no_doc_type", 1))
      .mockResolvedValue(response("no_doc_type", 0));
    api.patchMeta.mockResolvedValue({});
    open("no_doc_type");
    const select = await screen.findByRole("combobox", {
      name: t("hygiene.pickDocType", { title: "Architecture" }),
    });
    expect(within(counter(t("hygiene.listNoDocType"))).getByText("1")).toBeInTheDocument();

    fireEvent.change(select, { target: { value: "design" } });

    await waitFor(() => expect(api.patchMeta).toHaveBeenCalledWith("a1", { doc_type: "design" }));
    await waitFor(() =>
      expect(within(counter(t("hygiene.listNoDocType"))).getByText("0")).toBeInTheDocument(),
    );
    expect(api.getProjectHygiene).toHaveBeenCalledTimes(2);
    expect(toast).toHaveBeenCalledWith(t("hygiene.saved"), "success");
  });

  it("confirms an overdue document is still current", async () => {
    api.getProjectHygiene
      .mockResolvedValueOnce(response("review_overdue", 1))
      .mockResolvedValue(response("review_overdue", 0));
    api.markReviewed.mockResolvedValue({});
    open("review_overdue");
    fireEvent.click(await screen.findByRole("button", { name: t("assetMeta.stillCurrent") }));
    await waitFor(() => expect(api.markReviewed).toHaveBeenCalledWith("a1"));
    expect(await screen.findByText(t("hygiene.empty"))).toBeInTheDocument();
  });

  it("writes a missing description inline", async () => {
    api.getProjectHygiene
      .mockResolvedValueOnce(response("no_summary", 1))
      .mockResolvedValue(response("no_summary", 0));
    api.patchMeta.mockResolvedValue({});
    open("no_summary");
    fireEvent.click(await screen.findByRole("button", { name: t("assetMeta.addSummary") }));
    fireEvent.change(screen.getByRole("textbox", { name: t("hygiene.summaryFor", { title: "Architecture" }) }), {
      target: { value: "  Target architecture. " },
    });
    fireEvent.click(screen.getByRole("button", { name: t("common.save") }));
    await waitFor(() =>
      expect(api.patchMeta).toHaveBeenCalledWith("a1", { summary: "Target architecture." }),
    );
    expect(api.getAssetMeta).not.toHaveBeenCalled();
  });

  it("shows changed bases with a diff link and confirms them", async () => {
    api.getProjectHygiene.mockResolvedValue(response("basis_changed", 1));
    api.listRelations.mockResolvedValue({
      asset_id: "a1",
      incoming: {},
      outgoing: {
        derived_from: [
          { id: "r1", target_changed: true, target_version: 2, target_version_now: 4, other: { slug: "req", title: "Requirements" } },
          { id: "r2", target_changed: false, other: { slug: "old", title: "Unchanged" } },
        ],
      },
    });
    api.patchRelation.mockResolvedValue({});
    open("basis_changed");
    fireEvent.click(await screen.findByRole("button", { name: t("hygiene.showChanges") }));
    const bases = await screen.findByRole("list", { name: t("hygiene.changedBases") });
    expect(within(bases).queryByText("Unchanged")).toBeNull();
    expect(within(bases).getByRole("link", { name: t("hygiene.showChanges") })).toHaveAttribute(
      "href",
      "/v/req/diff?from=2&to=4",
    );
    fireEvent.click(within(bases).getByRole("button", { name: t("assetMeta.stillCurrent") }));
    await waitFor(() =>
      expect(api.patchRelation).toHaveBeenCalledWith("r1", { refresh_target_version: true }),
    );
    await waitFor(() => expect(api.getProjectHygiene).toHaveBeenCalledTimes(2));
  });

  it("repoints task links to the successor", async () => {
    api.getProjectHygiene.mockResolvedValue(response("superseded_linked", 1));
    api.listRelations.mockResolvedValue({
      asset_id: "a1",
      outgoing: {},
      incoming: { superseded_by: [{ id: "s", other: { id: "b2", slug: "new", title: "Architecture v2" } }] },
    });
    const ref = { id: "x1", system: "openproject", entity: "work_package", external_id: "7", external_scope: null, role: "context", required: true, label: "WP 7", url: null, note: null };
    const dup = { ...ref, id: "x2", external_id: "8" };
    api.listExternalRefs.mockResolvedValue([ref, dup]);
    api.addExternalRef
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new ApiError(409, "exists", "exists", "external_ref_exists"));
    api.deleteExternalRef.mockResolvedValue({ deleted: true });
    open("superseded_linked");
    fireEvent.click(await screen.findByRole("button", { name: t("hygiene.repoint") }));
    await waitFor(() => expect(api.deleteExternalRef).toHaveBeenCalledTimes(2));
    expect(confirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: t("hygiene.repointTitle", { name: "Architecture v2" }) }),
    );
    expect(api.addExternalRef).toHaveBeenCalledWith(
      "b2",
      expect.objectContaining({ system: "openproject", external_id: "7", required: true }),
    );
    await waitFor(() => expect(api.getProjectHygiene).toHaveBeenCalledTimes(2));
  });

  it("switches lists from the list switcher and keeps the list in the address", async () => {
    api.getProjectHygiene.mockResolvedValue(response("no_summary", 0));
    open("no_summary");
    await screen.findByText(t("hygiene.empty"));
    fireEvent.click(counter(t("hygiene.listHiddenEdges")));
    await waitFor(() => expect(api.getProjectHygiene).toHaveBeenLastCalledWith("p1", "hidden_edges", 1));
    expect(window.location.search).toBe("?list=hidden_edges");
    // `duplicates` appears only when the server counts it.
    expect(within(screen.getByRole("navigation", { name: t("hygiene.lists") })).queryByText(t("hygiene.listDuplicates"))).toBeNull();
  });

  it("shows no access for a viewer", async () => {
    api.getProjectHygiene.mockRejectedValue(new ApiError(404, "not found", "not found", "project_not_found"));
    open("no_summary");
    expect(await screen.findByText(t("viewerStates.noAccess"))).toBeInTheDocument();
  });

  it("is linked from the project tabs for owners and editors only", () => {
    const { rerender } = renderWithClient(<ProjectTabs slug="p1" tab="files" member canMaintain />);
    expect(screen.getByRole("link", { name: t("projectTabs.hygiene") })).toHaveAttribute(
      "href",
      "/projects/p1/hygiene",
    );
    rerender(<ProjectTabs slug="p1" tab="files" member />);
    expect(screen.queryByRole("link", { name: t("projectTabs.hygiene") })).toBeNull();
  });

  it("accepts a suggested duplicate pair", async () => {
    const pair = {
      certainty: "candidate" as const,
      similarity: 0.72,
      a: { id: "a1", slug: "doc1", title: "Architecture" },
      b: { id: "b2", slug: "doc2", title: "Architecture copy" },
    };
    api.getProjectHygiene
      .mockResolvedValueOnce(response("duplicates", 1, { items: [pair] }))
      .mockResolvedValue(response("duplicates", 0));
    api.markDuplicate.mockResolvedValue({ relation_id: "r" });
    open("duplicates");
    expect(await screen.findByRole("link", { name: "Architecture copy" })).toHaveAttribute("href", "/v/doc2");
    fireEvent.click(screen.getByRole("button", { name: t("hygiene.markDuplicate") }));
    await waitFor(() => expect(api.markDuplicate).toHaveBeenCalledWith("p1", "a1", "b2"));
    await waitFor(() =>
      expect(within(counter(t("hygiene.listDuplicates"))).getByText("0")).toBeInTheDocument(),
    );
  });
});
