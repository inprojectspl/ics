import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { AssetMetaDetail, AssetMetaView, AssetSummary } from "../api";
import { t } from "../lib/i18n";
import { AssetMetaSection } from "./AssetMetaSection";

const getAssetMeta = vi.fn();
const patchMeta = vi.fn();
const markReviewed = vi.fn();

vi.mock("../api", () => ({
  api: {
    getAssetMeta: (...a: unknown[]) => getAssetMeta(...a),
    patchMeta: (...a: unknown[]) => patchMeta(...a),
    markReviewed: (...a: unknown[]) => markReviewed(...a),
    listDocTypes: () => Promise.resolve([{ key: "design", label: "Design" }]),
  },
}));

function asset(over: Partial<AssetSummary> = {}): AssetSummary {
  return {
    id: "a1",
    slug: "doc",
    title: "Doc",
    kind: "md_single",
    size_bytes: 1,
    version: 3,
    security_status: "clean",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    my_role: "editor",
    ...over,
  };
}

function view(over: Partial<AssetMetaView> = {}): AssetMetaView {
  return {
    id: "a1",
    slug: "doc",
    title: "Doc",
    version: 3,
    content_updated_at: "2026-09-20T10:00:00Z",
    tags: [],
    project_id: null,
    access_role: "editor",
    summary: "Payment architecture.",
    summary_source: "human",
    doc_type: "design",
    freshness: "current",
    flags: [],
    maintainer: { id: "u1", email: "anna@example.com", display_name: "Anna" },
    review_due_at: "2027-01-01T00:00:00Z",
    reviewed_at: null,
    language: null,
    properties: {},
    ...over,
  };
}

function detail(over: Partial<AssetMetaDetail> = {}): AssetMetaDetail {
  return {
    id: "a1",
    version: 3,
    summary: "Payment architecture.",
    summary_source: "human",
    summary_version: 3,
    doc_type: "design",
    freshness: "current",
    flags: [],
    maintainer: { id: "u1", email: "anna@example.com", display_name: "Anna" },
    maintainer_id: null,
    review_due_at: "2027-09-26T00:00:00Z",
    reviewed_at: "2026-09-26T00:00:00Z",
    reviewed_by: "u1",
    language: "en",
    properties: {},
    ...over,
  };
}

function renderSection(a: AssetSummary = asset()) {
  const onChanged = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AssetMetaSection asset={a} onChanged={onChanged} />
    </QueryClientProvider>,
  );
  return { onChanged };
}

beforeEach(() => {
  getAssetMeta.mockReset().mockResolvedValue(view());
  patchMeta.mockReset();
  markReviewed.mockReset();
});

describe("AssetMetaSection", () => {
  it("shows the summary, doc type, maintainer and dates", async () => {
    renderSection();
    expect(await screen.findByText("Payment architecture.")).toBeInTheDocument();
    expect(await screen.findByText("Design")).toBeInTheDocument();
    expect(screen.getByText("Anna")).toBeInTheDocument();
    expect(screen.getByText(t("assetMeta.reviewDue"))).toBeInTheDocument();
    expect(screen.getByText(t("assetMeta.changed"))).toBeInTheDocument();
  });

  it("shows freshness and the content change date next to the description", async () => {
    getAssetMeta.mockResolvedValue(view({ freshness: "review_overdue", doc_type: "design" }));
    renderSection();
    expect(await screen.findByText(t("assetMeta.title"))).toBeInTheDocument();
    expect(await screen.findByText("Payment architecture.")).toBeInTheDocument();
    expect(await screen.findByText("Design")).toBeInTheDocument();
    expect(screen.getByText(t("freshness.reviewOverdue"))).toBeInTheDocument();
    expect(screen.getByText("Anna")).toBeInTheDocument();
    expect(document.querySelector('time[datetime="2026-09-20T10:00:00Z"]')).toHaveTextContent(/\S/);
  });

  it("gives editors the edit actions", async () => {
    getAssetMeta.mockResolvedValue(view({ summary: null, freshness: "review_overdue" }));
    renderSection();
    expect(await screen.findByRole("button", { name: t("assetMeta.addSummary") })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("assetMeta.stillCurrent") })).toBeInTheDocument();
  });

  it("gives viewers no edit actions", async () => {
    getAssetMeta.mockResolvedValue(view({ summary: null, freshness: "review_overdue" }));
    renderSection(asset({ my_role: "viewer" }));
    expect(await screen.findByText(t("assetMeta.noSummary"))).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("marks an agent summary and drops the mark after a human edit", async () => {
    getAssetMeta.mockResolvedValue(
      view({ summary_source: "agent", flags: ["summary_stale"] }),
    );
    patchMeta.mockResolvedValue(detail({ summary: "Written by a person.", summary_source: "human" }));
    const { onChanged } = renderSection();
    expect(await screen.findByText(t("assetMeta.byAgent"))).toBeInTheDocument();
    expect(screen.getByText(t("assetMeta.stale"))).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: t("assetMeta.editSummary") }));
    fireEvent.change(screen.getByLabelText(t("assetMeta.summaryLabel")), {
      target: { value: "Written by a person." },
    });
    fireEvent.click(screen.getByRole("button", { name: t("common.save") }));

    // The textarea carries the same text until the write finishes and closes it.
    await waitFor(() =>
      expect(screen.queryByLabelText(t("assetMeta.summaryLabel"))).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Written by a person.")).toBeInTheDocument();
    expect(patchMeta).toHaveBeenCalledWith("a1", { summary: "Written by a person." });
    expect(screen.queryByText(t("assetMeta.byAgent"))).not.toBeInTheDocument();
    expect(screen.queryByText(t("assetMeta.stale"))).not.toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("confirms an overdue document is still current and refreshes the badge", async () => {
    getAssetMeta.mockResolvedValue(view({ freshness: "review_overdue" }));
    markReviewed.mockResolvedValue(detail({ freshness: "current" }));
    const { onChanged } = renderSection();
    expect(await screen.findByText(t("freshness.reviewOverdue"))).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: t("assetMeta.stillCurrent") }));

    await waitFor(() => expect(markReviewed).toHaveBeenCalledWith("a1"));
    await waitFor(() =>
      expect(screen.queryByText(t("freshness.reviewOverdue"))).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: t("assetMeta.stillCurrent") })).toBeNull();
    expect(onChanged).toHaveBeenCalled();
  });
});
