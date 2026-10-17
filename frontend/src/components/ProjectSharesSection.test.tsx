import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { AssetSummary, ProjectShareRow, ProjectSummary } from "../api";
import { ApiError } from "../api/_core";
import { t } from "../lib/i18n";
import { ProjectSharesSection } from "./ProjectSharesSection";

const listProjectShares = vi.fn();
const putProjectShare = vi.fn();
const deleteProjectShare = vi.fn();
const listProjects = vi.fn();

vi.mock("../api", () => ({
  api: {
    listProjectShares: (...a: unknown[]) => listProjectShares(...a),
    putProjectShare: (...a: unknown[]) => putProjectShare(...a),
    deleteProjectShare: (...a: unknown[]) => deleteProjectShare(...a),
    listProjects: (...a: unknown[]) => listProjects(...a),
  },
}));

function project(id: string, name: string, my_role: ProjectSummary["my_role"]): ProjectSummary {
  return {
    id,
    slug: id,
    name,
    description: null,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    my_role,
    member_count: 1,
    asset_count: 1,
  };
}

function share(id: string, name: string, role: ProjectShareRow["role"] = "viewer"): ProjectShareRow {
  return { project_id: id, project_slug: id, project_name: name, role, created_at: null };
}

const asset = { id: "a1", slug: "doc", project_id: "home", my_role: "owner" } as AssetSummary;

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProjectSharesSection asset={asset} />
    </QueryClientProvider>,
  );
}

const list = () => within(screen.getByRole("list", { name: t("projectShares.listLabel") }));

beforeEach(() => {
  listProjectShares.mockReset().mockResolvedValue([share("ops", "Operations")]);
  listProjects.mockReset().mockResolvedValue({
    items: [
      project("home", "Home", "owner"),
      project("ops", "Operations", "editor"),
      project("sales", "Sales", "editor"),
      project("board", "Board", "viewer"),
    ],
    total: 4,
    page: 1,
    page_size: 200,
  });
  putProjectShare.mockReset();
  deleteProjectShare.mockReset();
});

describe("ProjectSharesSection", () => {
  it("offers only projects the caller can add to, without the home and assigned ones", async () => {
    renderSection();
    await screen.findByText("Operations");
    const picker = await screen.findByRole("radiogroup", { name: t("common.project") });
    expect(within(picker).getAllByRole("radio").map((r) => r.closest("label")?.textContent)).toEqual([expect.stringContaining("Sales")]);
  });

  it("adds a project with the chosen role and shows the updated list", async () => {
    putProjectShare.mockResolvedValue([share("ops", "Operations"), share("sales", "Sales", "editor")]);
    renderSection();
    await screen.findByRole("radiogroup", { name: t("common.project") });
    fireEvent.change(screen.getByLabelText(t("common.role")), { target: { value: "editor" } });
    fireEvent.click(screen.getByRole("button", { name: t("common.add") }));
    await waitFor(() => expect(list().getByText("Sales")).toBeInTheDocument());
    expect(putProjectShare).toHaveBeenCalledWith("a1", "sales", "editor");
    // Nothing left to add: the note comes after the assigned projects.
    expect(screen.getByText(t("projectShares.noMoreCandidates"))).toBeInTheDocument();
    expect(screen.queryByText(t("projectShares.noCandidates"))).toBeNull();
  });

  it("says once that there is no project at all to add the document to", async () => {
    listProjectShares.mockResolvedValue([]);
    listProjects.mockResolvedValue({ items: [project("home", "Home", "owner")], total: 1, page: 1, page_size: 200 });
    renderSection();
    expect(await screen.findByText(t("projectShares.noCandidates"))).toBeInTheDocument();
    expect(screen.queryByText(t("projectShares.none"))).toBeNull();
    expect(screen.queryByLabelText(t("common.project"))).toBeNull();
  });

  it("removes a project and updates the list", async () => {
    deleteProjectShare.mockResolvedValue([]);
    renderSection();
    await screen.findByText("Operations");
    fireEvent.click(
      screen.getByRole("button", { name: t("projectShares.removeLabel", { name: "Operations" }) }),
    );
    expect(await screen.findByText(t("projectShares.none"))).toBeInTheDocument();
    expect(deleteProjectShare).toHaveBeenCalledWith("a1", "ops");
  });

  it("shows the API error and keeps the list", async () => {
    putProjectShare.mockRejectedValue(new ApiError(400, "home", "home", "project_share_home"));
    renderSection();
    await screen.findByLabelText(t("common.project"));
    fireEvent.click(screen.getByRole("button", { name: t("common.add") }));
    expect(await screen.findByText(t("error.project_share_home"))).toBeInTheDocument();
    expect(list().getByText("Operations")).toBeInTheDocument();
  });
});
