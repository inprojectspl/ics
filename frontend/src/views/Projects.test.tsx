import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { ProjectSummary } from "../api";
import { t } from "../lib/i18n";
import { renderWithClient } from "../test-utils";
import { Projects } from "./Projects";

const listProjects = vi.fn();
const createProject = vi.fn();
const toast = vi.fn();
const navigate = vi.fn();

vi.mock("../api", () => ({
  api: {
    listProjects: (...a: unknown[]) => listProjects(...a),
    createProject: (...a: unknown[]) => createProject(...a),
  },
}));
vi.mock("../components/Toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("../lib/navigate", async (orig) => ({
  ...(await orig<typeof import("../lib/navigate")>()),
  navigate: (p: string) => navigate(p),
}));

function project(i: number, over: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: `p${i}`,
    slug: `project-${i}`,
    name: `Project ${i}`,
    description: null,
    created_by: "u1",
    created_at: `2026-01-${String(i).padStart(2, "0")}T00:00:00Z`,
    my_role: "owner",
    member_count: 2,
    asset_count: 3,
    ...over,
  };
}

function page(items: ProjectSummary[]) {
  return { items, total: items.length, page: 1, page_size: 200 };
}

const names = () => screen.queryAllByRole("link", { name: /^Project \d+$/ }).map((a) => a.textContent);
const row = (name: string) => screen.getByRole("link", { name }).closest("li") as HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/projects");
});

describe("Projects", () => {
  it("lists under the member filter only projects joined without owning them", async () => {
    listProjects.mockResolvedValue(
      page([
        project(1),
        project(2, { my_role: "editor" }),
        project(3, { my_role: "viewer" }),
        // An admin sees projects without a membership too.
        project(4, { my_role: null }),
      ]),
    );
    renderWithClient(<Projects />);
    await waitFor(() => expect(names()).toHaveLength(4));
    fireEvent.click(screen.getByRole("button", { name: /^Role:/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: t("projects.roleMember") }));
    expect(names()).toEqual(["Project 2", "Project 3"]);
  });

  it("shows a skeleton until the list arrives, asking for the whole list", async () => {
    let resolve: (v: unknown) => void = () => {};
    listProjects.mockReturnValue(new Promise((r) => (resolve = r)));
    const { container } = renderWithClient(<Projects />);
    expect(container.querySelector("[aria-hidden] ul")).not.toBeNull();
    resolve(page([project(1)]));
    await screen.findByRole("link", { name: "Project 1" });
    expect(listProjects).toHaveBeenCalledWith({ page_size: 200 });
    expect(screen.getByText("1 project")).toBeInTheDocument();
  });

  it("surfaces a load error with a retry", async () => {
    listProjects.mockRejectedValue(new Error("backend down"));
    renderWithClient(<Projects />);
    expect(await screen.findByText("backend down")).toBeInTheDocument();
    listProjects.mockResolvedValue(page([project(1)]));
    fireEvent.click(screen.getByRole("button", { name: t("common.retry") }));
    expect(await screen.findByRole("link", { name: "Project 1" })).toBeInTheDocument();
  });

  it("renders the empty state without repeating the create action", async () => {
    listProjects.mockResolvedValue(page([]));
    renderWithClient(<Projects />);
    expect(await screen.findByText("You have no projects yet")).toBeInTheDocument();
    expect(screen.queryByRole("toolbar")).toBeNull();
    expect(screen.getAllByRole("button", { name: t("projects.newProject") })).toHaveLength(1);
  });

  it("lists projects with description, counts and role", async () => {
    listProjects.mockResolvedValue(
      page([project(1, { description: "Specs", member_count: 1, asset_count: 1 }), project(2, { my_role: null })]),
    );
    renderWithClient(<Projects />);
    await screen.findByRole("link", { name: "Project 1" });
    const first = row("Project 1");
    expect(within(first).getByText("Specs")).toBeInTheDocument();
    expect(within(first).getAllByText("1 member").length).toBeGreaterThan(0);
    expect(within(first).getAllByText("1 document").length).toBeGreaterThan(0);
    expect(within(first).getByText("Owner")).toBeInTheDocument();
    const second = row("Project 2");
    expect(within(second).getByText(t("projects.noRole"))).toBeInTheDocument();
    expect(within(second).getAllByText("3 documents").length).toBeGreaterThan(0);
  });

  it("opens a project from its name and its views from the row menu", async () => {
    listProjects.mockResolvedValue(page([project(7)]));
    renderWithClient(<Projects />);
    fireEvent.click(await screen.findByRole("link", { name: "Project 7" }));
    expect(navigate).toHaveBeenCalledWith("/projects/project-7");

    fireEvent.click(screen.getByRole("button", { name: t("projectRow.actions", { name: "Project 7" }) }));
    fireEvent.click(screen.getByRole("menuitem", { name: t("projectTabs.map") }));
    expect(navigate).toHaveBeenLastCalledWith("/projects/project-7/map");
  });

  it("offers only the views a viewer may open", async () => {
    listProjects.mockResolvedValue(page([project(1, { my_role: "viewer" })]));
    renderWithClient(<Projects />);
    await screen.findByRole("link", { name: "Project 1" });
    fireEvent.click(screen.getByRole("button", { name: t("projectRow.actions", { name: "Project 1" }) }));
    expect(screen.queryByRole("menuitem", { name: t("projectTabs.hygiene") })).toBeNull();
    expect(screen.getByRole("menuitem", { name: t("projectTabs.agent") })).toBeInTheDocument();
  });

  it("searches, filters by role and sorts on the client", async () => {
    listProjects.mockResolvedValue(
      page([
        project(1, { name: "Project 1", asset_count: 1 }),
        project(2, { name: "Project 2", asset_count: 9, my_role: "editor", description: "legal" }),
        project(3, { name: "Project 3", asset_count: 5 }),
      ]),
    );
    renderWithClient(<Projects />);
    await waitFor(() => expect(names()).toEqual(["Project 1", "Project 2", "Project 3"]));

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "legal" } });
    expect(names()).toEqual(["Project 2"]);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "" } });

    fireEvent.click(screen.getByRole("button", { name: /^Role:/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: t("projects.roleOwned") }));
    expect(names()).toEqual(["Project 1", "Project 3"]);
    fireEvent.click(screen.getByRole("button", { name: /^Role:/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: t("projects.roleMember") }));
    expect(names()).toEqual(["Project 2"]);
    fireEvent.click(screen.getByRole("button", { name: /^Role:/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: t("projects.roleAll") }));

    fireEvent.click(screen.getByRole("button", { name: /^Sort by:/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: t("projects.sortDocuments") }));
    expect(names()).toEqual(["Project 2", "Project 3", "Project 1"]);
    fireEvent.click(screen.getByRole("button", { name: /^Sort by:/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: t("projects.sortCreated") }));
    expect(names()).toEqual(["Project 3", "Project 2", "Project 1"]);
  });

  it("shows a no-match state that clears the search", async () => {
    listProjects.mockResolvedValue(page([project(1)]));
    renderWithClient(<Projects />);
    await screen.findByRole("link", { name: "Project 1" });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "zzz" } });
    expect(screen.getByText(t("projects.noMatchesTitle"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("filters.clear") }));
    expect(names()).toEqual(["Project 1"]);
  });

  it("pages long lists 25 at a time", async () => {
    listProjects.mockResolvedValue(page(Array.from({ length: 30 }, (_, i) => project(i + 1, { name: `Project ${i + 1}` }))));
    renderWithClient(<Projects />);
    await waitFor(() => expect(names()).toHaveLength(25));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(names()).toHaveLength(5);
  });

  describe("create dialog", () => {
    beforeEach(() => {
      listProjects.mockResolvedValue(page([]));
    });

    async function openDialog() {
      renderWithClient(<Projects />);
      await screen.findByText("You have no projects yet");
      fireEvent.click(screen.getAllByRole("button", { name: t("projects.newProject") })[0]!);
      return screen.getByRole("dialog", { name: t("projects.newProject") });
    }

    it("opens for `?new=1` and drops the parameter", async () => {
      window.history.replaceState({}, "", "/projects?new=1");
      renderWithClient(<Projects />);
      expect(await screen.findByRole("dialog", { name: t("projects.newProject") })).toBeInTheDocument();
      expect(window.location.search).toBe("");
    });

    it("keeps submit disabled for a blank name", async () => {
      const dialog = await openDialog();
      fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "   " } });
      expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();
      fireEvent.submit(within(dialog).getByRole("button", { name: "Create" }).closest("form")!);
      expect(createProject).not.toHaveBeenCalled();
    });

    it("creates a trimmed project and navigates to it", async () => {
      createProject.mockResolvedValue(project(9, { slug: "fresh" }));
      const dialog = await openDialog();
      fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "  Fresh  " } });
      fireEvent.change(within(dialog).getByLabelText(/Description \(optional\)/), { target: { value: " Docs " } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Create" }));
      await waitFor(() => expect(navigate).toHaveBeenCalledWith("/projects/fresh"));
      expect(createProject).toHaveBeenCalledWith("Fresh", "Docs");
      expect(toast).toHaveBeenCalledWith("Project created", "success");
      expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("keeps the dialog open with the error on failure", async () => {
      createProject.mockRejectedValue(new Error("network"));
      const dialog = await openDialog();
      fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Dup" } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Create" }));
      expect(await within(dialog).findByRole("alert")).toBeInTheDocument();
      expect(navigate).not.toHaveBeenCalled();
      expect(within(dialog).getByLabelText("Name")).toHaveValue("Dup");
    });

    it("closes on cancel", async () => {
      const dialog = await openDialog();
      fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });
});
