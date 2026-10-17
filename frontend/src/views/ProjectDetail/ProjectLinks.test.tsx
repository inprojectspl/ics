import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { KeyDocument } from "../../api";
import { ApiError } from "../../api/_core";
import { t } from "../../lib/i18n";
import { moveItem } from "./KeyDocuments";
import { ProjectLinks } from "./ProjectLinks";
import { renderWithClient } from "../../test-utils";

const getKeyDocuments = vi.fn();
const putKeyDocuments = vi.fn();
const getProjectExternalRefs = vi.fn();
const putProjectExternalRefs = vi.fn();
const searchAssets = vi.fn();

vi.mock("../../api", () => ({
  api: {
    getKeyDocuments: (...a: unknown[]) => getKeyDocuments(...a),
    putKeyDocuments: (...a: unknown[]) => putKeyDocuments(...a),
    getProjectExternalRefs: (...a: unknown[]) => getProjectExternalRefs(...a),
    putProjectExternalRefs: (...a: unknown[]) => putProjectExternalRefs(...a),
    searchAssets: (...a: unknown[]) => searchAssets(...a),
  },
}));

function doc(id: string, title: string, position: number, reason: string | null = null): KeyDocument {
  return {
    id,
    asset_id: id,
    slug: `s${id}`,
    title,
    kind: "md_single",
    doc_type: null,
    freshness: "current",
    summary: null,
    estimated_tokens: null,
    position,
    reason,
  };
}

const docs = [doc("a", "Goals", 0, "Start here"), doc("b", "Requirements", 1), doc("c", "Design", 2)];

beforeEach(() => {
  getKeyDocuments.mockReset().mockResolvedValue(docs);
  putKeyDocuments.mockReset().mockImplementation(async (_slug: string, entries: { asset_id: string }[]) =>
    entries.map((e, i) => ({ ...docs.find((d) => d.asset_id === e.asset_id), position: i })),
  );
  getProjectExternalRefs.mockReset().mockResolvedValue([
    { system: "openproject", external_id: "acme" },
    { system: "project_standard", external_id: "ps-1" },
  ]);
  putProjectExternalRefs.mockReset();
  searchAssets.mockReset().mockResolvedValue([]);
});

const titles = () =>
  within(screen.getByRole("list", { name: t("projectLinks.keyTitle") }))
    .getAllByRole("link")
    .map((a) => a.textContent);

describe("ProjectLinks for the owner", () => {
  it("moving a document sends the whole list in the new order", async () => {
    renderWithClient(<ProjectLinks slug="p" canEdit />);
    await screen.findByText("Requirements");
    fireEvent.click(screen.getByRole("button", { name: t("projectLinks.moveUp", { title: "Requirements" }) }));
    await waitFor(() =>
      expect(putKeyDocuments).toHaveBeenCalledWith("p", [
        { asset_id: "b", reason: null },
        { asset_id: "a", reason: "Start here" },
        { asset_id: "c", reason: null },
      ]),
    );
    await waitFor(() => expect(titles()).toEqual(["Requirements", "Goals", "Design"]));
  });

  it("removes a document and adds one from the search", async () => {
    searchAssets.mockResolvedValue([{ id: "d", slug: "sd", title: "Report" }, { id: "a", slug: "sa", title: "Goals" }]);
    renderWithClient(<ProjectLinks slug="p" canEdit />);
    await screen.findByText("Design");
    fireEvent.click(screen.getByRole("button", { name: t("projectLinks.remove", { title: "Design" }) }));
    await waitFor(() =>
      expect(putKeyDocuments).toHaveBeenLastCalledWith("p", [
        { asset_id: "a", reason: "Start here" },
        { asset_id: "b", reason: null },
      ]),
    );

    fireEvent.change(screen.getByLabelText(t("projectLinks.searchLabel")), { target: { value: "rep" } });
    fireEvent.click(screen.getByRole("button", { name: t("projectLinks.search") }));
    const results = within(await screen.findByRole("list", { name: t("projectLinks.searchResults") }));
    // Documents already on the list are not offered again.
    expect(results.queryByText("Goals")).not.toBeInTheDocument();
    fireEvent.click(results.getByRole("button", { name: t("common.add") }));
    await waitFor(() =>
      expect(putKeyDocuments).toHaveBeenLastCalledWith("p", [
        { asset_id: "a", reason: "Start here" },
        { asset_id: "b", reason: null },
        { asset_id: "d", reason: null },
      ]),
    );
  });

  it("validates the OpenProject identifier and keeps other systems on save", async () => {
    putProjectExternalRefs.mockRejectedValue(
      new ApiError(409, "taken", "taken", "project_external_taken"),
    );
    renderWithClient(<ProjectLinks slug="p" canEdit />);
    const input = await screen.findByLabelText(t("projectLinks.openProject"));
    expect(input).toHaveValue("acme");

    fireEvent.change(input, { target: { value: "-bad id" } });
    expect(screen.getByText(t("projectLinks.externalInvalid"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("projectLinks.saveExternal") })).toBeDisabled();

    fireEvent.change(input, { target: { value: "acme-app" } });
    fireEvent.click(screen.getByRole("button", { name: t("projectLinks.saveExternal") }));
    await waitFor(() =>
      expect(putProjectExternalRefs).toHaveBeenCalledWith("p", [
        { system: "project_standard", external_id: "ps-1" },
        { system: "openproject", external_id: "acme-app" },
      ]),
    );
    expect(await screen.findByText(t("error.project_external_taken"))).toBeInTheDocument();
  });
});

describe("ProjectLinks for a member", () => {
  it("shows both sections read-only", async () => {
    renderWithClient(<ProjectLinks slug="p" canEdit={false} />);
    expect(await screen.findByText("Start here")).toBeInTheDocument();
    expect(await screen.findByText("acme")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("search")).not.toBeInTheDocument();
  });
});

describe("moveItem", () => {
  it("moves within bounds and ignores moves past the ends", () => {
    expect(moveItem(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
    expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"]);
    expect(moveItem(["a", "b"], 1, 1)).toEqual(["a", "b"]);
  });
});
