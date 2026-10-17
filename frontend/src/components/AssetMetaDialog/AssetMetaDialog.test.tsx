import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { AssetMetaView, DocTypeInfo } from "../../api";
import { ApiError } from "../../api/_core";
import { setLocale, t } from "../../lib/i18n";
import { AssetMetaDialog } from "./AssetMetaDialog";

const patchMeta = vi.fn();
const setTags = vi.fn();

function docType(key: string, label: string, properties: Record<string, unknown>): DocTypeInfo {
  return {
    key,
    label,
    agent_hint: null,
    default_review_days: null,
    properties_schema: { type: "object", properties },
    position: 0,
    archived: false,
    archived_at: null,
  };
}

const types = [
  docType("contract", "Contract", { client: { type: "string", title: "Client" } }),
  docType("report", "Report", { period: { type: "string", format: "date", title: "Period" } }),
];

vi.mock("../../api", () => ({
  api: {
    listDocTypes: () => Promise.resolve(types),
    patchMeta: (...a: unknown[]) => patchMeta(...a),
    setTags: (...a: unknown[]) => setTags(...a),
  },
}));

const meta: AssetMetaView = {
  id: "a1",
  slug: "doc",
  title: "ACME contract",
  version: 2,
  content_updated_at: null,
  tags: ["acme"],
  project_id: null,
  access_role: "owner_file",
  summary: "Framework agreement.",
  summary_source: "human",
  doc_type: "contract",
  freshness: "current",
  flags: [],
  maintainer: { id: "u1", email: "anna@example.com", display_name: "Anna" },
  review_due_at: null,
  reviewed_at: null,
  language: "en",
  properties: { client: "ACME" },
};

function renderDialog() {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AssetMetaDialog
        assetId="a1"
        meta={meta}
        people={[{ id: "u1", label: "Anna" }, { id: "u2", label: "Bob" }]}
        onClose={onClose}
        onSaved={onSaved}
      />
    </QueryClientProvider>,
  );
  return { onSaved, onClose };
}

const save = () => fireEvent.click(screen.getByRole("button", { name: t("common.save") }));

beforeEach(() => {
  patchMeta.mockReset().mockResolvedValue({ id: "a1" });
  setTags.mockReset().mockResolvedValue({ id: "a1", tags: [] });
});

describe("AssetMetaDialog", () => {
  it("suggests a language code that fits the interface language", async () => {
    try {
      setLocale("en", { persist: false });
      renderDialog();
      expect(await screen.findByLabelText(t("assetMetaDialog.language"))).toHaveAttribute("placeholder", "en");
      cleanup();
      setLocale("pl", { persist: false });
      renderDialog();
      expect(await screen.findByLabelText(t("assetMetaDialog.language"))).toHaveAttribute("placeholder", "pl");
    } finally {
      setLocale("en", { persist: false });
    }
  });

  it("rebuilds the property fields when the doc type changes", async () => {
    renderDialog();
    expect(await screen.findByLabelText("Client")).toHaveValue("ACME");
    fireEvent.change(screen.getByLabelText(t("assetMetaDialog.docType")), {
      target: { value: "report" },
    });
    expect(screen.queryByLabelText("Client")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Period")).toHaveAttribute("type", "date");
  });

  it("sends only the fields that changed", async () => {
    const { onSaved } = renderDialog();
    await screen.findByLabelText("Client");
    fireEvent.change(screen.getByLabelText(t("assetMeta.summaryLabel")), {
      target: { value: "Framework agreement for 2027." },
    });
    fireEvent.change(screen.getByLabelText(t("assetMeta.maintainer")), { target: { value: "u2" } });
    save();
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchMeta).toHaveBeenCalledWith("a1", {
      summary: "Framework agreement for 2027.",
      maintainer_id: "u2",
    });
    expect(setTags).not.toHaveBeenCalled();
  });

  it("sends the rebuilt properties with a new doc type and the tags separately", async () => {
    const { onSaved } = renderDialog();
    await screen.findByLabelText("Client");
    fireEvent.change(screen.getByLabelText(t("assetMetaDialog.docType")), {
      target: { value: "report" },
    });
    fireEvent.change(screen.getByLabelText("Period"), { target: { value: "2026-09-30" } });
    fireEvent.change(screen.getByLabelText(t("assetMetaDialog.tags")), {
      target: { value: "acme, Q3" },
    });
    save();
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(patchMeta).toHaveBeenCalledWith("a1", {
      doc_type: "report",
      properties: { period: "2026-09-30" },
    });
    expect(setTags).toHaveBeenCalledWith("a1", ["acme", "q3"]);
  });

  it("closes without a request when nothing changed", async () => {
    const { onClose } = renderDialog();
    await screen.findByLabelText("Client");
    save();
    expect(onClose).toHaveBeenCalled();
    expect(patchMeta).not.toHaveBeenCalled();
  });

  it("highlights the field named by metadata_invalid", async () => {
    patchMeta.mockRejectedValue(
      new ApiError(400, "properties.client: bad", "bad", "metadata_invalid", "properties.client"),
    );
    renderDialog();
    const client = await screen.findByLabelText("Client");
    fireEvent.change(client, { target: { value: "X" } });
    save();
    expect(await screen.findByRole("alert")).toHaveTextContent(t("error.metadata_invalid"));
    expect(client).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText(t("assetMetaDialog.language"))).not.toHaveAttribute("aria-invalid");
  });
});
