import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import type { AssetSummary } from "../api";
import { setLocale, t } from "../lib/i18n";
import { renderWithClient } from "../test-utils";
import { MoveToProjectDialog } from "./MoveToProjectDialog";

vi.mock("../api", () => ({
  api: {
    listProjects: vi.fn(),
    patchAssetProject: vi.fn().mockResolvedValue(undefined),
  },
}));
vi.mock("./Toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));

const { api } = await import("../api");

const PROJECTS = [
  { id: "p1", name: "Alpha", slug: "alpha", my_role: "owner" },
  { id: "p2", name: "Beta", slug: "beta", my_role: "editor" },
  { id: "p3", name: "Gamma", slug: "gamma", my_role: "observer" },
];

function mkAsset(over: Partial<AssetSummary> = {}): AssetSummary {
  return { slug: "my-doc", title: "Doc", project_id: null, ...over } as AssetSummary;
}

beforeEach(() => {
  vi.mocked(api.listProjects).mockResolvedValue({ items: PROJECTS, total: 3 } as never);
  vi.mocked(api.patchAssetProject).mockResolvedValue(undefined as never);
});

describe("MoveToProjectDialog", () => {
  it("lists only projects the caller can add to", async () => {
    renderWithClient(<MoveToProjectDialog asset={mkAsset()} onClose={() => {}} onUpdated={() => {}} />);
    expect(await screen.findByRole("radio", { name: /Alpha/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Beta/ })).toBeInTheDocument();
    // Gamma (observer role) is filtered out.
    expect(screen.queryByRole("radio", { name: /Gamma/ })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: t("moveToProject.noProject") })).toBeChecked();
  });

  it("saves the picked project only on Save, then closes", async () => {
    const onUpdated = vi.fn();
    const onClose = vi.fn();
    renderWithClient(<MoveToProjectDialog asset={mkAsset()} onClose={onClose} onUpdated={onUpdated} />);
    const alpha = await screen.findByRole("radio", { name: /Alpha/ });
    const save = screen.getByRole("button", { name: t("common.save") });
    expect(save).toBeDisabled();
    fireEvent.click(alpha);
    expect(api.patchAssetProject).not.toHaveBeenCalled();
    fireEvent.click(save);
    await waitFor(() => expect(api.patchAssetProject).toHaveBeenCalledWith("my-doc", "p1"));
    expect(onUpdated).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("takes the document out of its project", async () => {
    renderWithClient(
      <MoveToProjectDialog asset={mkAsset({ project_id: "p1" })} onClose={() => {}} onUpdated={() => {}} />,
    );
    fireEvent.click(await screen.findByRole("radio", { name: t("moveToProject.noProject") }));
    fireEvent.click(screen.getByRole("button", { name: t("common.save") }));
    await waitFor(() => expect(api.patchAssetProject).toHaveBeenCalledWith("my-doc", null));
  });

  it("finds a project by a part of its name, ignoring diacritics", async () => {
    const many = ["Café legal", "Portal", "Contracts", "People", "Purchasing", "Sales"].map((name, i) => ({
      id: `m${i}`, name, slug: `m${i}`, my_role: "owner",
    }));
    vi.mocked(api.listProjects).mockResolvedValue({ items: many, total: many.length } as never);
    renderWithClient(<MoveToProjectDialog asset={mkAsset()} onClose={() => {}} onUpdated={() => {}} />);
    fireEvent.change(await screen.findByRole("searchbox", { name: t("filters.searchProject") }), { target: { value: "cafe" } });
    expect(screen.getAllByRole("radio").map((r) => r.closest("label")?.textContent)).toEqual([expect.stringContaining("Café legal")]);
  });

  it("shows a hint when there are no projects", async () => {
    vi.mocked(api.listProjects).mockResolvedValue({ items: [], total: 0 } as never);
    renderWithClient(<MoveToProjectDialog asset={mkAsset()} onClose={() => {}} onUpdated={() => {}} />);
    expect(await screen.findByText(/You have no projects/)).toBeInTheDocument();
  });

  it("a failed project load leaves the dialog working with an empty list", async () => {
    vi.mocked(api.listProjects).mockRejectedValue(new Error("boom"));
    renderWithClient(<MoveToProjectDialog asset={mkAsset()} onClose={() => {}} onUpdated={() => {}} />);
    expect(await screen.findByText(/You have no projects/)).toBeInTheDocument();
  });

  it("renders in English", async () => {
    setLocale("en", { persist: false });
    vi.mocked(api.listProjects).mockResolvedValue({ items: PROJECTS, total: 3 } as never);
    renderWithClient(<MoveToProjectDialog asset={mkAsset()} onClose={() => {}} onUpdated={() => {}} />);
    expect(await screen.findByRole("radio", { name: /Alpha/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "No project" })).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" })).toBeInTheDocument();
  });
});
