import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { RelationItem, RelationList } from "../../api";
import { ApiError } from "../../api/_core";
import { t } from "../../lib/i18n";
import { RelationsPanel } from "./RelationsPanel";

const listRelations = vi.fn();
const patchRelation = vi.fn();
const deleteRelation = vi.fn();
const addRelation = vi.fn();
const searchAssets = vi.fn();

vi.mock("../../api", () => ({
  api: {
    listRelations: (...a: unknown[]) => listRelations(...a),
    patchRelation: (...a: unknown[]) => patchRelation(...a),
    deleteRelation: (...a: unknown[]) => deleteRelation(...a),
    addRelation: (...a: unknown[]) => addRelation(...a),
    searchAssets: (...a: unknown[]) => searchAssets(...a),
    getOutline: () => Promise.resolve({ kind: "md_single", headings: [] }),
    listDocTypes: () => Promise.resolve([{ key: "business_goals", label: "Business goals" }]),
  },
}));

function item(over: Partial<RelationItem> = {}): RelationItem {
  return {
    id: "r1",
    relation_type: "derived_from",
    label: "derived_from",
    source_id: "a1",
    target_id: "b1",
    source_path: null,
    target_path: null,
    target_anchor: null,
    target_version: 2,
    target_version_now: 4,
    target_changed: true,
    note: "Workshop requirements",
    origin: "agent",
    created_at: null,
    other: {
      id: "b1",
      slug: "goals",
      title: "Project goals",
      kind: "md_single",
      doc_type: "business_goals",
      freshness: "current",
      summary: null,
      estimated_tokens: null,
    },
    ...over,
  };
}

const list: RelationList = {
  asset_id: "a1",
  outgoing: { derived_from: [item()] },
  incoming: {
    referenced_by: [
      item({
        id: "r2",
        relation_type: "references",
        label: "referenced_by",
        target_changed: false,
        note: null,
        origin: "extracted",
        other: { ...item().other, id: "c1", slug: "notes", title: "Notes", doc_type: null },
      }),
    ],
  },
};

function renderPanel(canEdit: boolean, slug = "spec", assetId = "a1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RelationsPanel slug={slug} assetId={assetId} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  listRelations.mockReset().mockResolvedValue(list);
  patchRelation.mockReset().mockResolvedValue({});
  deleteRelation.mockReset().mockResolvedValue({ deleted: true });
  addRelation.mockReset().mockResolvedValue({});
  searchAssets.mockReset().mockResolvedValue([]);
});

describe("RelationsPanel", () => {
  it("groups relations by type and direction with their labels", async () => {
    renderPanel(false);
    expect(await screen.findByText("Project goals")).toBeInTheDocument();
    expect(screen.getByText(t("relation.derivedFrom"))).toBeInTheDocument();
    expect(screen.getByText(t("relation.referencedBy"))).toBeInTheDocument();
    expect(screen.getByText("Workshop requirements")).toBeInTheDocument();
    expect(screen.getByText(t("relations.originAgent"))).toBeInTheDocument();
    expect(await screen.findByText("Business goals")).toBeInTheDocument();
  });

  it("confirms a changed basis as still current and drops the warning", async () => {
    renderPanel(true);
    expect(await screen.findByText(t("relations.basisChanged", { from: 2, to: 4 }))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: t("relations.showChanges") })).toHaveAttribute(
      "href",
      "/v/goals/diff?from=2&to=4",
    );
    fireEvent.click(screen.getByRole("button", { name: t("relations.stillCurrent") }));
    await waitFor(() =>
      expect(patchRelation).toHaveBeenCalledWith("r1", { refresh_target_version: true }),
    );
    await waitFor(() =>
      expect(screen.queryByText(t("relations.basisChanged", { from: 2, to: 4 }))).not.toBeInTheDocument(),
    );
  });

  it("warns about a changed basis only for derived_from, like the Hygiene flag", async () => {
    listRelations.mockResolvedValue({
      asset_id: "a1",
      outgoing: { depends_on: [item({ relation_type: "depends_on", label: "depends_on" })] },
      incoming: {},
    });
    renderPanel(true);
    expect(await screen.findByText("Project goals")).toBeInTheDocument();
    expect(screen.queryByText(t("relations.basisChanged", { from: 2, to: 4 }))).not.toBeInTheDocument();
  });

  it("gives editors add and remove actions", async () => {
    renderPanel(true);
    await screen.findByText("Project goals");
    expect(screen.getByRole("button", { name: t("relations.addTitle") })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("relations.removeLabel", { title: "Notes" }) }));
    await waitFor(() => expect(deleteRelation).toHaveBeenCalledWith("r2"));
    await waitFor(() => expect(listRelations).toHaveBeenCalledTimes(2));
  });

  it("gives readers no add, remove or confirm actions", async () => {
    renderPanel(false);
    await screen.findByText("Project goals");
    expect(screen.queryByRole("button", { name: t("relations.addTitle") })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove the relation/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t("relations.stillCurrent") })).not.toBeInTheDocument();
    // Seeing what changed is not an edit.
    expect(screen.getByRole("link", { name: t("relations.showChanges") })).toBeInTheDocument();
  });

  it("adds derived_from from the dialog and both documents show it with their labels", async () => {
    const empty: RelationList = { asset_id: "a1", outgoing: {}, incoming: {} };
    const edge = item({ note: null, target_changed: false, origin: "manual" });
    const fromSource: RelationList = { asset_id: "a1", outgoing: { derived_from: [edge] }, incoming: {} };
    const fromTarget: RelationList = {
      asset_id: "b1",
      outgoing: {},
      incoming: {
        basis_for: [
          item({
            ...edge,
            label: "basis_for",
            other: { ...edge.other, id: "a1", slug: "spec", title: "Specification", doc_type: null },
          }),
        ],
      },
    };
    listRelations.mockImplementation(async (slug: string) =>
      slug === "goals" ? fromTarget : addRelation.mock.calls.length ? fromSource : empty,
    );
    searchAssets.mockResolvedValue([
      { id: "b1", slug: "goals", title: "Project goals", kind: "md_single" },
    ]);

    const source = renderPanel(true);
    expect(await screen.findByText(t("relations.none"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("relations.addTitle") }));
    fireEvent.change(screen.getByLabelText(t("relations.targetLabel")), { target: { value: "goals" } });
    const results = within(await screen.findByRole("list", { name: t("addRelation.results") }));
    fireEvent.click(results.getByText("Project goals"));
    expect(screen.getByLabelText(t("relations.typeLabel"))).toHaveValue("derived_from");
    fireEvent.click(screen.getByRole("button", { name: t("relations.add") }));

    await waitFor(() =>
      expect(addRelation).toHaveBeenCalledWith("a1", { relation_type: "derived_from", target_id: "b1" }),
    );
    expect(await screen.findByText("Derived from")).toBeInTheDocument();
    expect(screen.getByText("Project goals")).toBeInTheDocument();
    source.unmount();

    renderPanel(false, "goals", "b1");
    expect(await screen.findByText("Basis for")).toBeInTheDocument();
    expect(screen.getByText("Specification")).toBeInTheDocument();
    expect(screen.queryByText("Derived from")).not.toBeInTheDocument();
  });

  it("renders nothing without graph access (404)", async () => {
    listRelations.mockRejectedValue(new ApiError(404, "asset not found", "asset not found", "asset_not_found"));
    const { container } = renderPanel(true);
    await waitFor(() => expect(listRelations).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});

