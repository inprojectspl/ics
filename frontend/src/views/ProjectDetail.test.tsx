import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { AssetSummary, Me, ProjectDetail as Project, ProjectMemberRow, ProjectSummary } from "../api";
import { t } from "../lib/i18n";
import { ProjectDetail } from "./ProjectDetail";
import { renderWithClient } from "../test-utils";

const getProject = vi.fn();
const listProjects = vi.fn();
const inviteProjectMember = vi.fn();
const kickProjectMember = vi.fn();
const patchProjectMember = vi.fn();
const transferProjectOwner = vi.fn();
const leaveProject = vi.fn();
const deleteProject = vi.fn();
const patchProject = vi.fn();
const toast = vi.fn();
const confirm = vi.fn();
const navigate = vi.fn();
const useAssetUpload = vi.fn();

vi.mock("../api", () => ({
  api: {
    getProject: (...a: unknown[]) => getProject(...a),
    listProjects: (...a: unknown[]) => listProjects(...a),
    inviteProjectMember: (...a: unknown[]) => inviteProjectMember(...a),
    kickProjectMember: (...a: unknown[]) => kickProjectMember(...a),
    patchProjectMember: (...a: unknown[]) => patchProjectMember(...a),
    transferProjectOwner: (...a: unknown[]) => transferProjectOwner(...a),
    leaveProject: (...a: unknown[]) => leaveProject(...a),
    deleteProject: (...a: unknown[]) => deleteProject(...a),
    patchProject: (...a: unknown[]) => patchProject(...a),
    listDocTypes: vi.fn().mockResolvedValue([]),
    getKeyDocuments: vi.fn().mockResolvedValue([]),
    getProjectExternalRefs: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock("../components/WatchToggle", () => ({ ProjectWatchToggle: () => null }));
vi.mock("../components/Toast", () => ({ useToast: () => ({ toast }), useErrorToast: () => vi.fn() }));
vi.mock("../components/ConfirmDialog", () => ({ useConfirm: () => confirm }));
vi.mock("../lib/navigate", async (orig) => ({
  ...(await orig<typeof import("../lib/navigate")>()),
  navigate: (p: string) => navigate(p),
}));
vi.mock("../lib/useAssetUpload", () => ({
  useAssetUpload: (opts: unknown) => useAssetUpload(opts),
}));

const me = { id: "u1", email: "me@example.com", display_name: "Me", role: "user" } as Me;

function member(i: number, over: Partial<ProjectMemberRow> = {}): ProjectMemberRow {
  return {
    id: `m${i}`,
    user_id: `u${i}`,
    email: `user${i}@example.com`,
    display_name: null,
    role: "editor",
    invited_at: "2026-01-01T00:00:00Z",
    accepted_at: "2026-01-02T00:00:00Z",
    invited_by: "u1",
    ...over,
  };
}

const asset = {
  id: "a1",
  slug: "doc-one",
  title: "Doc One",
  kind: "md_single",
  size_bytes: 100,
  version: 1,
  security_status: "clean",
  active_share_modes: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  my_role: "owner",
} as AssetSummary;

function proj(over: Partial<Project> = {}): Project {
  return {
    id: "p1",
    slug: "alpha",
    name: "Alpha",
    description: "First project",
    created_by: "u1",
    created_at: "2026-01-01T00:00:00Z",
    my_role: "owner",
    member_count: 3,
    asset_count: 0,
    members: [
      member(1, { role: "owner", display_name: "Me", email: "me@example.com" }),
      member(2, { display_name: "Bob" }),
      member(3, { role: "viewer", accepted_at: null }),
    ],
    assets: [],
    ...over,
  };
}

/** The frame (heading, role) reads the project from the list query. */
function listed(p: Project) {
  const { members: _m, assets: _a, assets_truncated: _t, ...summary } = p;
  listProjects.mockResolvedValue({ items: [summary as ProjectSummary], total: 1, page: 1, page_size: 200 });
}

function setProject(p: Project) {
  getProject.mockResolvedValue(p);
  listed(p);
}

function renderView(user: Me = me, tab?: "members" | "settings") {
  window.history.replaceState({}, "", `/projects/alpha${tab ? `?tab=${tab}` : ""}`);
  return renderWithClient(<ProjectDetail me={user} slug="alpha" />);
}

function row(email: string): HTMLElement {
  const li = screen.getAllByText(email).at(-1)?.closest("li");
  if (!li) throw new Error(`no row for ${email}`);
  return li;
}

const moreLabel = t("projectDetail.moreActions", { name: "Alpha" });

async function openMore() {
  fireEvent.click(await screen.findByRole("button", { name: moreLabel }));
  return screen.getByRole("menu");
}

async function memberMenu(name: string) {
  fireEvent.click(screen.getByRole("button", { name: t("projectMembers.actions", { name }) }));
  return screen.getByRole("menu");
}

beforeEach(() => {
  for (const f of [
    getProject,
    listProjects,
    inviteProjectMember,
    kickProjectMember,
    patchProjectMember,
    transferProjectOwner,
    leaveProject,
    deleteProject,
    patchProject,
    toast,
    navigate,
  ]) {
    f.mockReset();
  }
  confirm.mockReset().mockResolvedValue(true);
  useAssetUpload.mockReset().mockReturnValue({ uploading: false, onDrop: vi.fn(), onPicked: vi.fn() });
  setProject(proj());
});

afterEach(() => {
  window.history.replaceState({}, "", "/");
});

describe("ProjectDetail states", () => {
  it("shows a skeleton while the project loads", async () => {
    let resolve: (v: Project) => void = () => {};
    getProject.mockReturnValue(new Promise((r) => (resolve = r)));
    const { container } = renderView();
    expect(container.querySelector("[aria-hidden] .skeleton")).not.toBeNull();
    resolve(proj());
    expect(await screen.findByRole("heading", { name: "Alpha" })).toBeInTheDocument();
    await screen.findByText(t("projectDetail.emptyTitle"));
    expect(getProject).toHaveBeenCalledWith("alpha", { key: "updated", order: "desc" });
  });

  it("shows the no-access screen when loading fails", async () => {
    getProject.mockRejectedValue(new Error("403 Forbidden"));
    renderView();
    expect(await screen.findAllByText(t("viewerStates.noAccess"))).not.toHaveLength(0);
    expect(screen.getByText("You are not allowed to do this.")).toBeInTheDocument();
  });

  it("offers upload in an empty project only from the header", async () => {
    renderView();
    expect(await screen.findByText(t("projectDetail.emptyContrib"))).toBeInTheDocument();
    // Header action plus the empty state's own button.
    expect(screen.getAllByRole("button", { name: t("upload.action") })).toHaveLength(1);
    // Uploads from this page are scoped to the loaded project.
    expect(useAssetUpload).toHaveBeenLastCalledWith(expect.objectContaining({ projectId: "p1" }));
  });

  it("opens the upload dialog for this project", async () => {
    renderView();
    fireEvent.click((await screen.findAllByRole("button", { name: t("upload.action") }))[0] as HTMLElement);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(t("upload.toProject", { name: "Alpha" }))).toBeInTheDocument();
  });

  it("hides upload and owner controls from viewers", async () => {
    setProject(proj({ my_role: "viewer" }));
    renderView();
    expect(await screen.findByText(t("projectDetail.empty"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t("upload.action") })).toBeNull();
    expect(screen.queryByRole("button", { name: t("common.invite") })).toBeNull();
    const menu = await openMore();
    expect(within(menu).getByRole("menuitem", { name: t("projectDetail.leave") })).toBeInTheDocument();
    expect(within(menu).queryByRole("menuitem", { name: t("projectDetail.deleteProject") })).toBeNull();
    expect(within(menu).queryByRole("menuitem", { name: t("projectHeader.editTitle") })).toBeNull();
  });

  it("lets editors upload but not manage members", async () => {
    setProject(proj({ my_role: "editor" }));
    renderView(me, "members");
    await screen.findByText("Bob");
    expect(screen.getByRole("button", { name: t("upload.action") })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t("common.invite") })).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
    const menu = await openMore();
    expect(within(menu).getByRole("menuitem", { name: t("projectDetail.leave") })).toBeInTheDocument();
  });

  it("gives a sys-admin outside the project the owner controls", async () => {
    setProject(proj({ my_role: null }));
    renderView({ ...me, id: "admin", role: "admin" });
    await screen.findByRole("heading", { name: "Alpha" });
    expect(await screen.findByRole("button", { name: t("common.invite") })).toBeInTheDocument();
    const menu = await openMore();
    expect(within(menu).getByRole("menuitem", { name: t("projectDetail.deleteProject") })).toBeInTheDocument();
    expect(within(menu).queryByRole("menuitem", { name: t("projectDetail.leave") })).toBeNull();
  });

  it("renders the project's documents", async () => {
    setProject(proj({ assets: [asset], assets_truncated: true }));
    renderView();
    expect(await screen.findByRole("link", { name: "Doc One" })).toHaveAttribute("href", "/v/doc-one");
    expect(screen.getByText(t("projectDetail.truncated", { count: 1 }))).toBeInTheDocument();
  });

  it("renders members with their roles on the members tab", async () => {
    renderView(me, "members");
    await screen.findByText("Bob");
    const self = row("me@example.com");
    expect(within(self).getByText(t("projectDetail.you"))).toBeInTheDocument();
    // Role names come from the catalogue, not the raw API value.
    expect(within(self).getByText(t("common.roleOwner"))).toBeInTheDocument();
    expect(within(self).queryByText("owner")).toBeNull();
    // Nobody can demote or kick themselves or the owner.
    expect(within(self).queryByRole("combobox")).toBeNull();

    const pending = row("user3@example.com");
    expect(within(pending).getByText(t("projectMembers.pending"))).toBeInTheDocument();
    // Ownership can only go to someone who accepted the invite.
    const pendingMenu = await memberMenu("user3@example.com");
    expect(within(pendingMenu).queryByRole("menuitem", { name: t("projectMembers.transfer") })).toBeNull();
    fireEvent.keyDown(pendingMenu, { key: "Escape" });
    const bobMenu = await memberMenu("Bob");
    expect(within(bobMenu).getByRole("menuitem", { name: t("projectMembers.transfer") })).toBeInTheDocument();
  });
});

describe("ProjectDetail member actions", () => {
  async function openInvite() {
    fireEvent.click(await screen.findByRole("button", { name: t("common.invite") }));
    return screen.getByRole("dialog");
  }

  it("invites a member with the picked role and reloads", async () => {
    inviteProjectMember.mockResolvedValue(member(4));
    renderView();
    const dialog = await openInvite();
    const submit = within(dialog).getByRole("button", { name: t("common.invite") });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(t("common.email")), { target: { value: "  new@example.com " } });
    fireEvent.click(within(dialog).getByRole("radio", { name: new RegExp(t("common.roleViewer")) }));
    fireEvent.click(submit);

    await waitFor(() => expect(toast).toHaveBeenCalledWith(t("projectDetail.inviteSent"), "success"));
    expect(inviteProjectMember).toHaveBeenCalledWith("alpha", "new@example.com", "viewer");
    expect(getProject).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the invite dialog open when the invite fails", async () => {
    inviteProjectMember.mockRejectedValue(new Error("network"));
    renderView();
    const dialog = await openInvite();
    const email = within(dialog).getByLabelText(t("common.email"));
    fireEvent.change(email, { target: { value: "x@example.com" } });
    fireEvent.submit(email.closest("form") as HTMLFormElement);
    await waitFor(() => expect(toast).toHaveBeenCalledWith(t("projectDetail.inviteFailed"), "error"));
    expect(within(dialog).getByLabelText(t("common.email"))).toHaveValue("x@example.com");
    expect(within(dialog).getByRole("button", { name: t("common.invite") })).toBeEnabled();
  });

  it("closes the invite dialog on cancel", async () => {
    renderView();
    const dialog = await openInvite();
    fireEvent.click(within(dialog).getByRole("button", { name: t("common.cancel") }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("kicks a member after confirmation", async () => {
    kickProjectMember.mockResolvedValue({ kicked: true });
    renderView(me, "members");
    await screen.findByText("Bob");
    fireEvent.click(within(await memberMenu("Bob")).getByRole("menuitem", { name: t("projectMembers.remove") }));
    await waitFor(() => expect(kickProjectMember).toHaveBeenCalledWith("alpha", "u2"));
    expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ destructive: true }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(t("projectDetail.kicked"), "success"));
    expect(getProject).toHaveBeenCalledTimes(2);
  });

  it("does nothing when the kick is not confirmed", async () => {
    confirm.mockResolvedValue(false);
    renderView(me, "members");
    await screen.findByText("Bob");
    fireEvent.click(within(await memberMenu("Bob")).getByRole("menuitem", { name: t("projectMembers.remove") }));
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(kickProjectMember).not.toHaveBeenCalled();
  });

  it("disables member controls while a kick is in flight", async () => {
    let resolve: (v: unknown) => void = () => {};
    kickProjectMember.mockReturnValue(new Promise((r) => (resolve = r)));
    renderView(me, "members");
    await screen.findByText("Bob");
    fireEvent.click(within(await memberMenu("Bob")).getByRole("menuitem", { name: t("projectMembers.remove") }));
    const pendingRole = () => screen.getByRole("combobox", { name: t("projectMembers.roleOf", { name: "user3@example.com" }) });
    await waitFor(() => expect(pendingRole()).toBeDisabled());
    expect(screen.getByRole("button", { name: t("common.invite") })).toBeDisabled();
    resolve({ kicked: true });
    await waitFor(() => expect(pendingRole()).toBeEnabled());
  });

  it("toasts when a kick fails", async () => {
    kickProjectMember.mockRejectedValue(new Error("404 Not Found"));
    renderView(me, "members");
    await screen.findByText("Bob");
    fireEvent.click(within(await memberMenu("Bob")).getByRole("menuitem", { name: t("projectMembers.remove") }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringMatching(/^Not found/), "error"));
  });

  it("changes a member role", async () => {
    patchProjectMember.mockResolvedValue(member(2, { role: "viewer" }));
    renderView(me, "members");
    await screen.findByText("Bob");
    fireEvent.change(screen.getByRole("combobox", { name: t("projectMembers.roleOf", { name: "Bob" }) }), {
      target: { value: "viewer" },
    });
    await waitFor(() => expect(patchProjectMember).toHaveBeenCalledWith("alpha", "u2", "viewer"));
    await waitFor(() => expect(getProject).toHaveBeenCalledTimes(2));
  });

  it("toasts when a role change fails", async () => {
    patchProjectMember.mockRejectedValue(new Error("boom"));
    renderView(me, "members");
    await screen.findByText("Bob");
    fireEvent.change(screen.getByRole("combobox", { name: t("projectMembers.roleOf", { name: "Bob" }) }), {
      target: { value: "viewer" },
    });
    await waitFor(() => expect(toast).toHaveBeenCalledWith("boom", "error"));
  });

  it("transfers ownership after confirmation", async () => {
    transferProjectOwner.mockResolvedValue({ transferred: true });
    renderView(me, "members");
    await screen.findByText("Bob");
    fireEvent.click(within(await memberMenu("Bob")).getByRole("menuitem", { name: t("projectMembers.transfer") }));
    await waitFor(() => expect(transferProjectOwner).toHaveBeenCalledWith("alpha", "u2"));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(t("projectDetail.transferred"), "success"));
  });

  it("skips the transfer when not confirmed and toasts on failure", async () => {
    confirm.mockResolvedValueOnce(false);
    transferProjectOwner.mockRejectedValue(new Error("409 Conflict"));
    renderView(me, "members");
    await screen.findByText("Bob");
    fireEvent.click(within(await memberMenu("Bob")).getByRole("menuitem", { name: t("projectMembers.transfer") }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(transferProjectOwner).not.toHaveBeenCalled();

    fireEvent.click(within(await memberMenu("Bob")).getByRole("menuitem", { name: t("projectMembers.transfer") }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringMatching(/^Conflict/), "error"));
  });
});

describe("ProjectDetail project actions", () => {
  async function pick(label: string) {
    fireEvent.click(within(await openMore()).getByRole("menuitem", { name: label }));
  }

  it("leaves the project and goes back to the list", async () => {
    setProject(proj({ my_role: "editor" }));
    leaveProject.mockResolvedValue({ left: true });
    renderView();
    await pick(t("projectDetail.leave"));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/projects"));
    expect(leaveProject).toHaveBeenCalledWith("alpha");
    expect(toast).toHaveBeenCalledWith(t("projectDetail.left"), "success");
  });

  it("stays when leaving fails", async () => {
    setProject(proj({ my_role: "viewer" }));
    leaveProject.mockRejectedValue(new Error("boom"));
    renderView();
    await pick(t("projectDetail.leave"));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("boom", "error"));
    expect(navigate).not.toHaveBeenCalled();
  });

  it("does not leave without confirmation", async () => {
    setProject(proj({ my_role: "viewer" }));
    confirm.mockResolvedValue(false);
    renderView();
    await pick(t("projectDetail.leave"));
    await waitFor(() => expect(confirm).toHaveBeenCalled());
    expect(leaveProject).not.toHaveBeenCalled();
  });

  it("deletes the project after confirmation", async () => {
    deleteProject.mockResolvedValue({ deleted: true });
    renderView();
    await pick(t("projectDetail.deleteProject"));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/projects"));
    expect(deleteProject).toHaveBeenCalledWith("alpha");
    expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ title: t("projectDetail.deleteTitle", { name: "Alpha" }) }));
  });

  it("keeps the page when deletion fails or is cancelled", async () => {
    confirm.mockResolvedValueOnce(false);
    deleteProject.mockRejectedValue(new Error("boom"));
    renderView();
    await pick(t("projectDetail.deleteProject"));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(deleteProject).not.toHaveBeenCalled();

    await pick(t("projectDetail.deleteProject"));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("boom", "error"));
    expect(navigate).not.toHaveBeenCalled();
  });

  it("saves edited name and description", async () => {
    patchProject.mockResolvedValue(proj({ name: "Beta" }));
    renderView();
    await pick(t("projectHeader.editTitle"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(t("projectHeader.nameLabel")), { target: { value: "Beta" } });
    fireEvent.change(within(dialog).getByLabelText(t("projects.descriptionOptional")), { target: { value: "" } });
    setProject(proj({ name: "Beta", description: null }));
    fireEvent.click(within(dialog).getByRole("button", { name: t("common.save") }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(t("projectDetail.saved"), "success"));
    expect(patchProject).toHaveBeenCalledWith("alpha", { name: "Beta", description: null });
    expect(await screen.findByRole("heading", { name: "Beta" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps the editor open when saving fails", async () => {
    patchProject.mockRejectedValue(new Error("network"));
    renderView();
    await pick(t("projectHeader.editTitle"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(t("projectHeader.nameLabel")), { target: { value: "Beta" } });
    fireEvent.click(within(dialog).getByRole("button", { name: t("common.save") }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(t("projectDetail.saveFailed"), "error"));
    expect(within(screen.getByRole("dialog")).getByLabelText(t("projectHeader.nameLabel"))).toHaveValue("Beta");
  });
});
