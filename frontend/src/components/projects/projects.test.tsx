import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { Me, ProjectSummary } from "../../api";
import { api } from "../../api";
import { ApiError } from "../../api/_core";
import { t, tn } from "../../lib/i18n";
import * as nav from "../../lib/navigate";
import { renderWithClient } from "../../test-utils";
import { mockMedia } from "../../test-media";
import { ToastProvider } from "../Toast";
import { EditProjectDialog } from "../../views/ProjectDetail/EditProjectDialog";
import { InviteMemberDialog } from "../../views/ProjectDetail/InviteMemberDialog";
import { CreateProjectDialog } from "./CreateProjectDialog";
import { ProjectFrame } from "./ProjectFrame";
import { ProjectMonogram } from "./ProjectMonogram";
import { ProjectRoleBadge } from "./ProjectRoleBadge";
import { ProjectRow } from "./ProjectRow";

function mk(over: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: "p1",
    slug: "alpha",
    name: "Alpha Beta",
    description: "Project description",
    created_by: null,
    created_at: "2026-09-01T00:00:00Z",
    my_role: "owner",
    member_count: 3,
    asset_count: 12,
    ...over,
  };
}

const me: Me = { id: "u1", email: "a@x.pl", display_name: null, role: "user", dev_stub_sso: false, locale: null };

beforeEach(() => {
  mockMedia({ width: 1440 });
  localStorage.clear();
});

describe("ProjectRow", () => {
  it("opens the project from its name and shows size, people and role", () => {
    render(
      <ul>
        <ProjectRow project={mk()} />
      </ul>,
    );
    expect(screen.getByRole("link", { name: "Alpha Beta" })).toHaveAttribute("href", "/projects/alpha");
    expect(screen.getByText("Project description")).toBeInTheDocument();
    expect(screen.getAllByText(tn("documents.count", 12)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(tn("projects.memberCount", 3)).length).toBeGreaterThan(0);
    expect(screen.getByText(t("common.roleOwner"))).toBeInTheDocument();
  });

  it("the menu holds the views the role may open", () => {
    const go = vi.spyOn(nav, "navigate").mockImplementation(() => {});
    const { rerender } = render(
      <ul>
        <ProjectRow project={mk()} />
      </ul>,
    );
    const open = () => fireEvent.click(screen.getByRole("button", { name: t("projectRow.actions", { name: "Alpha Beta" }) }));
    open();
    const items = () => within(screen.getByRole("menu")).getAllByRole("menuitem").map((b) => b.textContent);
    expect(items()).toEqual([t("common.open"), t("projectTabs.map"), t("projectTabs.hygiene"), t("projectTabs.agent")]);
    fireEvent.click(screen.getByRole("menuitem", { name: t("projectTabs.map") }));
    expect(go).toHaveBeenCalledWith("/projects/alpha/map");
    rerender(
      <ul>
        <ProjectRow project={mk({ my_role: "viewer" })} />
      </ul>,
    );
    open();
    expect(items()).toEqual([t("common.open"), t("projectTabs.map"), t("projectTabs.agent")]);
    fireEvent.keyDown(document, { key: "Escape" });
    rerender(
      <ul>
        <ProjectRow project={mk({ my_role: null })} />
      </ul>,
    );
    open();
    expect(items()).toEqual([t("common.open")]);
  });
});

describe("ProjectRoleBadge and ProjectMonogram", () => {
  it("says no membership in words", () => {
    render(<ProjectRoleBadge role={null} />);
    expect(screen.getByTitle(t("projects.noRoleTitle"))).toHaveTextContent(t("projects.noRole"));
  });

  it("uses two letters of the name", () => {
    const { container, rerender } = render(<ProjectMonogram name="Alpha Beta" />);
    expect(container).toHaveTextContent("AB");
    rerender(<ProjectMonogram name="mwars" size="lg" />);
    expect(container).toHaveTextContent("MW");
  });
});

describe("CreateProjectDialog", () => {
  it("creates the project and goes into it", async () => {
    const create = vi.spyOn(api, "createProject").mockResolvedValue(mk({ slug: "new" }));
    const go = vi.spyOn(nav, "navigate").mockImplementation(() => {});
    const onCreated = vi.fn();
    const onClose = vi.fn();
    render(
      <ToastProvider>
        <CreateProjectDialog onClose={onClose} onCreated={onCreated} />
      </ToastProvider>,
    );
    const submit = screen.getByRole("button", { name: t("common.create") });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: t("common.name") }), { target: { value: " New " } });
    fireEvent.change(screen.getByRole("textbox", { name: t("projects.descriptionOptional") }), { target: { value: "Why" } });
    fireEvent.click(submit);
    await waitFor(() => expect(go).toHaveBeenCalledWith("/projects/new"));
    expect(create).toHaveBeenCalledWith("New", "Why");
    expect(onCreated).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps the form and says why when the API refuses", async () => {
    vi.spyOn(api, "createProject").mockRejectedValue(new ApiError(409, "exists", "exists", "project_name_taken"));
    render(
      <ToastProvider>
        <CreateProjectDialog onClose={vi.fn()} onCreated={vi.fn()} />
      </ToastProvider>,
    );
    fireEvent.change(screen.getByRole("textbox", { name: t("common.name") }), { target: { value: "X" } });
    fireEvent.click(screen.getByRole("button", { name: t("common.create") }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("common.create") })).toBeEnabled();
  });
});

describe("InviteMemberDialog and EditProjectDialog", () => {
  it("invites with the picked role and closes on success", async () => {
    const onInvite = vi.fn().mockResolvedValue(true);
    const onClose = vi.fn();
    render(<InviteMemberDialog projectName="Alpha" busy={false} onInvite={onInvite} onClose={onClose} />);
    fireEvent.change(screen.getByRole("textbox", { name: t("common.email") }), { target: { value: "b@x.pl" } });
    fireEvent.click(screen.getByRole("radio", { name: new RegExp(t("common.roleViewer")) }));
    fireEvent.click(screen.getByRole("button", { name: t("common.invite") }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onInvite).toHaveBeenCalledWith("b@x.pl", "viewer");
  });

  it("stays open when the invitation fails", async () => {
    const onClose = vi.fn();
    render(<InviteMemberDialog projectName="Alpha" busy={false} onInvite={vi.fn().mockResolvedValue(false)} onClose={onClose} />);
    fireEvent.change(screen.getByRole("textbox", { name: t("common.email") }), { target: { value: "b@x.pl" } });
    fireEvent.click(screen.getByRole("button", { name: t("common.invite") }));
    await new Promise((r) => setTimeout(r, 0));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("saves name and description, and keeps the draft when saving fails", async () => {
    const onSave = vi.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValueOnce(undefined);
    const onClose = vi.fn();
    render(<EditProjectDialog name="Alpha" description={null} busy={false} onSave={onSave} onClose={onClose} />);
    fireEvent.change(screen.getByRole("textbox", { name: t("projectHeader.nameLabel") }), { target: { value: "Beta" } });
    fireEvent.click(screen.getByRole("button", { name: t("common.save") }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith("Beta", null));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: t("projects.descriptionOptional") }), { target: { value: "Description" } });
    fireEvent.click(screen.getByRole("button", { name: t("common.save") }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onSave).toHaveBeenLastCalledWith("Beta", "Description");
  });
});

describe("ProjectFrame", () => {
  it("heads the project, lists its local tabs by role and remembers it as recent", async () => {
    vi.spyOn(api, "listProjects").mockResolvedValue({ items: [mk()], total: 1, page: 1, page_size: 200 } as Awaited<
      ReturnType<typeof api.listProjects>
    >);
    renderWithClient(
      <ProjectFrame me={me} slug="alpha" tab="members">
        <p>members</p>
      </ProjectFrame>,
    );
    expect(await screen.findByRole("heading", { level: 1, name: "Alpha Beta" })).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: t("projectTabs.label") });
    expect(within(tabs).getByRole("link", { name: t("projectTabs.members") })).toHaveAttribute("aria-current", "page");
    expect(within(tabs).getByRole("link", { name: t("projectTabs.settings") })).toHaveAttribute("href", "/projects/alpha?tab=settings");
    // The breadcrumb names the tab under the project.
    expect(screen.getAllByRole("link", { name: "Alpha Beta" })[0]).toHaveAttribute("href", "/projects/alpha");
    expect(JSON.parse(localStorage.getItem("ics-recent-projects") ?? "[]")).toContain("alpha");
    expect(screen.getByText("members")).toBeInTheDocument();
  });

  it("a reader sees no settings or upkeep tabs", async () => {
    vi.spyOn(api, "listProjects").mockResolvedValue({ items: [mk({ my_role: "viewer" })], total: 1, page: 1, page_size: 200 } as Awaited<
      ReturnType<typeof api.listProjects>
    >);
    renderWithClient(
      <ProjectFrame me={me} slug="alpha" tab="files">
        <p>x</p>
      </ProjectFrame>,
    );
    const tabs = await screen.findByRole("navigation", { name: t("projectTabs.label") });
    expect(within(tabs).queryByRole("link", { name: t("projectTabs.settings") })).not.toBeInTheDocument();
    expect(within(tabs).queryByRole("link", { name: t("projectTabs.hygiene") })).not.toBeInTheDocument();
    expect(screen.getByText("Project description")).toBeInTheDocument();
  });
});
