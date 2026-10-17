import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { AssetSummary } from "../api";
import { ApiError } from "../api/_core";
import { t } from "../lib/i18n";
import { AddRelationDialog } from "./AddRelationDialog";

const searchAssets = vi.fn();
const getOutline = vi.fn();
const addRelation = vi.fn();

vi.mock("../api", () => ({
  api: {
    searchAssets: (...a: unknown[]) => searchAssets(...a),
    getOutline: (...a: unknown[]) => getOutline(...a),
    addRelation: (...a: unknown[]) => addRelation(...a),
  },
}));

function asset(id: string, slug: string, title: string, kind: AssetSummary["kind"] = "md_single"): AssetSummary {
  return {
    id,
    slug,
    title,
    kind,
    size_bytes: 1,
    version: 1,
    security_status: "clean",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

const self = asset("a1", "spec", "Specification");
const goals = asset("b1", "goals", "Business goals");
const manual = asset("c1", "manual", "Manual", "md_collection");

function renderDialog() {
  const onAdded = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AddRelationDialog assetId="a1" slug="spec" onClose={vi.fn()} onAdded={onAdded} />
    </QueryClientProvider>,
  );
  return { onAdded };
}

async function search(text: string) {
  fireEvent.change(screen.getByLabelText(t("relations.targetLabel")), { target: { value: text } });
  return within(await screen.findByRole("list", { name: t("addRelation.results") }));
}

beforeEach(() => {
  searchAssets.mockReset().mockResolvedValue([self, goals, manual]);
  getOutline.mockReset().mockImplementation(async (slug: string) =>
    slug === "manual"
      ? {
          kind: "md_collection",
          files: [
            { path: "setup.md", headings: [{ level: 1, text: "Installation", line: 1, anchor: "installation" }] },
            { path: "faq.md", headings: [] },
          ],
        }
      : {
          kind: "md_single",
          headings: [
            { level: 1, text: "Goals", line: 1, anchor: "goals" },
            { level: 2, text: "Metrics", line: 5, anchor: "metrics" },
          ],
        },
  );
  addRelation.mockReset().mockResolvedValue({});
});

describe("AddRelationDialog", () => {
  it("never offers the current document as the target", async () => {
    renderDialog();
    const results = await search("spe");
    expect(results.queryByText("Specification")).not.toBeInTheDocument();
    expect(results.getByText("Business goals")).toBeInTheDocument();
  });

  it("sends the chosen target, type and heading", async () => {
    const { onAdded } = renderDialog();
    fireEvent.click((await search("goals")).getByText("Business goals"));
    fireEvent.change(screen.getByLabelText(t("relations.typeLabel")), { target: { value: "depends_on" } });
    expect(screen.getByText(t("addRelation.hintDependsOn"))).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText(t("addRelation.heading")), { target: { value: "metrics" } });
    fireEvent.change(screen.getByLabelText(t("addRelation.note")), { target: { value: " from the workshop " } });
    fireEvent.click(screen.getByRole("button", { name: t("relations.add") }));

    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    expect(addRelation).toHaveBeenCalledWith("a1", {
      relation_type: "depends_on",
      target_id: "b1",
      target_anchor: "metrics",
      note: "from the workshop",
    });
  });

  it("picks a file of a collection and a heading inside it", async () => {
    renderDialog();
    fireEvent.click((await search("inst")).getByText("Manual"));
    fireEvent.change(await screen.findByLabelText(t("addRelation.file")), { target: { value: "setup.md" } });
    fireEvent.change(screen.getByLabelText(t("addRelation.heading")), { target: { value: "installation" } });
    fireEvent.click(screen.getByRole("button", { name: t("relations.add") }));
    await waitFor(() =>
      expect(addRelation).toHaveBeenCalledWith("a1", {
        relation_type: "derived_from",
        target_id: "c1",
        target_path: "setup.md",
        target_anchor: "installation",
      }),
    );
  });

  it("does not offer a heading for a symmetric relation", async () => {
    renderDialog();
    fireEvent.click((await search("goals")).getByText("Business goals"));
    await screen.findByLabelText(t("addRelation.heading"));
    fireEvent.change(screen.getByLabelText(t("relations.typeLabel")), { target: { value: "relates_to" } });
    expect(screen.queryByLabelText(t("addRelation.heading"))).not.toBeInTheDocument();
  });

  it.each(["relation_cycle", "relation_exists", "relation_limit"])(
    "shows the catalogue message for %s",
    async (code) => {
      addRelation.mockRejectedValue(new ApiError(409, "nope", "nope", code));
      const { onAdded } = renderDialog();
      fireEvent.click((await search("goals")).getByText("Business goals"));
      fireEvent.click(screen.getByRole("button", { name: t("relations.add") }));
      expect(await screen.findByRole("alert")).toHaveTextContent(t(`error.${code}` as Parameters<typeof t>[0]));
      expect(onAdded).not.toHaveBeenCalled();
    },
  );
});
