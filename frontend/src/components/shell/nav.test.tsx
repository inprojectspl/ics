import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, renderHook, screen, within } from "@testing-library/react";
import type { Me, ProjectSummary } from "../../api";
import { api } from "../../api";
import { t } from "../../lib/i18n";
import { renderWithClient } from "../../test-utils";
import { rememberProject } from "../../lib/recentProjects";
import { mockMedia } from "../../test-media";
import { AppSidebar } from "./AppSidebar";
import { navTree, sectionOf } from "./navModel";
import { PageContext } from "./PageContext";
import { ShellContext, type ShellApi } from "./shellContext";
import { useSidebarLayout } from "./useSidebarLayout";

const admin: Me = { id: "u1", email: "a@x.pl", display_name: "Ala Admin", role: "admin", dev_stub_sso: false, locale: null };
const user: Me = { ...admin, id: "u2", role: "user" };

function project(over: Partial<ProjectSummary>): ProjectSummary {
  return {
    id: "p1",
    slug: "p1",
    name: "Alpha",
    description: null,
    created_by: null,
    created_at: "2026-09-01T00:00:00Z",
    my_role: "owner",
    member_count: 1,
    asset_count: 0,
    ...over,
  };
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  localStorage.clear();
});

describe("navModel", () => {
  it("gives administration only to admins", () => {
    expect(navTree(admin, []).map((g) => g.id)).toEqual(["documents", "projects", "admin"]);
    expect(navTree(user, []).map((g) => g.id)).toEqual(["documents", "projects"]);
  });

  it("matches document scopes by the query and projects by their path", () => {
    const [docs, projects] = navTree(user, [{ slug: "abc", name: "ABC" }]);
    const mine = docs?.children.find((c) => c.id === "documents:state:mine");
    expect(mine?.match({ pathname: "/", search: new URLSearchParams("f=state:mine") })).toBe(true);
    expect(mine?.match({ pathname: "/", search: new URLSearchParams("") })).toBe(false);
    const all = docs?.children.find((c) => c.id === "documents:all");
    expect(all?.match({ pathname: "/", search: new URLSearchParams("f=type:pdf_doc") })).toBe(true);
    const abc = projects?.children.find((c) => c.id === "project:abc");
    expect(abc?.match({ pathname: "/projects/abc/map", search: new URLSearchParams() })).toBe(true);
    expect(abc?.match({ pathname: "/projects/abcd", search: new URLSearchParams() })).toBe(false);
  });

  it("lists the graph explorer under documents, whatever its start point", () => {
    const [docs] = navTree(user, []);
    const graph = docs?.children.find((c) => c.id === "documents:graph");
    expect(graph?.href).toBe("/graph");
    expect(graph?.match({ pathname: "/graph", search: new URLSearchParams("doc=abc") })).toBe(true);
    expect(sectionOf("/graph")).toBe("documents");
  });

  it("maps paths to sections", () => {
    expect(sectionOf("/")).toBe("documents");
    expect(sectionOf("/v/x")).toBe("documents");
    expect(sectionOf("/projects/x")).toBe("projects");
    expect(sectionOf("/admin/users")).toBe("admin");
    expect(sectionOf("/account/tokens")).toBe("account");
    expect(sectionOf("/notifications")).toBe("notifications");
    expect(sectionOf("/login")).toBeNull();
  });
});

describe("useSidebarLayout", () => {
  it("desktop follows the stored preference, tablet shows the rail, phone hides it", () => {
    mockMedia({ width: 1440 });
    const { result } = renderHook(() => useSidebarLayout(false));
    expect(result.current.mode).toBe("expanded");
    act(() => result.current.toggleCollapsed());
    expect(result.current.mode).toBe("rail");
    expect(localStorage.getItem("ics-sidebar")).toBe("collapsed");

    mockMedia({ width: 900 });
    expect(renderHook(() => useSidebarLayout(false)).result.current.mode).toBe("rail");
    mockMedia({ width: 390 });
    const phone = renderHook(() => useSidebarLayout(false)).result;
    expect(phone.current.mode).toBe("hidden");
    act(() => phone.current.openDrawer());
    expect(phone.current.drawerOpen).toBe(true);
    act(() => phone.current.closeDrawer());
    expect(phone.current.drawerOpen).toBe(false);
  });

  it("reading focus hides the column", () => {
    mockMedia({ width: 1440 });
    expect(renderHook(() => useSidebarLayout(true)).result.current.mode).toBe("hidden");
  });
});

function shell(over: Partial<ShellApi> = {}): ShellApi {
  return { contextSlot: null, focusMode: false, setFocusMode: vi.fn(), setActiveHref: vi.fn(), signedIn: true, ...over };
}

describe("PageContext", () => {
  it("renders the trail into the shell slot with the current page marked", () => {
    const slot = document.createElement("div");
    document.body.appendChild(slot);
    const api = shell({ contextSlot: slot });
    const { unmount } = render(
      <ShellContext.Provider value={api}>
        <PageContext
          crumbs={[{ label: "Projects", href: "/projects" }, { label: "Alpha", href: "/projects/a" }, { label: "File" }]}
          actions={<button type="button">Watch</button>}
          activeHref="/projects/a"
        />
      </ShellContext.Provider>,
    );
    const nav = within(slot).getByRole("navigation", { name: t("chrome.breadcrumbs") });
    // Phone shortcut: the way up is the nearest parent with a link.
    const links = within(nav).getAllByRole("link", { name: "Alpha" });
    expect(links[0]).toHaveAttribute("href", "/projects/a");
    expect(within(nav).getAllByText("File")[0]).toHaveAttribute("aria-current", "page");
    expect(within(slot).getByRole("button", { name: "Watch" })).toBeInTheDocument();
    expect(api.setActiveHref).toHaveBeenCalledWith("/projects/a");
    unmount();
    expect(api.setActiveHref).toHaveBeenLastCalledWith(null);
    slot.remove();
  });

  it("renders inline without a slot and nothing without content", () => {
    const { container, rerender } = render(<PageContext crumbs={[{ label: "Alone" }]} />);
    expect(screen.getAllByText("Alone").length).toBeGreaterThan(0);
    rerender(<PageContext />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("AppSidebar", () => {
  beforeEach(() => {
    vi.spyOn(api, "listProjects").mockResolvedValue({
      items: [project({ id: "p1", slug: "alpha", name: "Alpha" }), project({ id: "p2", slug: "beta", name: "Beta" })],
      total: 2,
      page: 1,
      page_size: 200,
    } as Awaited<ReturnType<typeof api.listProjects>>);
    vi.spyOn(api, "myQuota").mockResolvedValue({ used_bytes: 850, quota_bytes: 1000 });
  });

  it("marks the current view, lists projects and shows the storage meter", async () => {
    window.history.replaceState({}, "", "/?f=state:mine");
    renderWithClient(<AppSidebar me={admin} variant="expanded" activeHref={null} onToggleCollapsed={vi.fn()} />);
    expect(screen.getByRole("navigation", { name: t("nav.label") })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: t("sidebarNav.mine") })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByRole("link", { name: "Beta" })).toHaveAttribute("href", "/projects/beta");
    expect(screen.getByRole("link", { name: t("nav.adminUsers") })).toBeInTheDocument();
    expect(await screen.findByRole("progressbar", { name: t("quota.usage") })).toHaveAttribute("aria-valuenow", "85");
  });

  it("keeps opened projects in name order, with all projects last", async () => {
    rememberProject("alpha");
    rememberProject("beta");
    renderWithClient(<AppSidebar me={user} variant="expanded" activeHref={null} />);
    await screen.findByRole("link", { name: "Beta" });
    const group = screen.getByRole("link", { name: "Beta" }).closest("ul");
    expect(within(group as HTMLElement).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Alpha",
      "Beta",
      t("nav.allProjects"),
    ]);
  });

  it("the page can mark an entry the address cannot tell", async () => {
    renderWithClient(<AppSidebar me={user} variant="expanded" activeHref="/projects/alpha" />);
    expect(await screen.findByRole("link", { name: "Alpha" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: t("nav.adminUsers") })).not.toBeInTheDocument();
  });

  it("folds a group with its chevron and remembers it", () => {
    renderWithClient(<AppSidebar me={user} variant="expanded" activeHref={null} />);
    const toggle = screen.getByRole("button", { name: t("shell.collapseGroup", { name: t("nav.documents") }) });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: t("shell.expandGroup", { name: t("nav.documents") }) })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(JSON.parse(localStorage.getItem("ics-nav-folded") ?? "[]")).toEqual(["documents"]);
  });

  it("closes the drawer after a route was picked", () => {
    const onNavigate = vi.fn();
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    renderWithClient(<AppSidebar me={user} variant="drawer" activeHref={null} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByRole("link", { name: t("nav.allProjects") }));
    expect(onNavigate).toHaveBeenCalled();
    expect(window.location.pathname).toBe("/projects");
  });

  it("in the rail a group opens its entries in a flyout menu", () => {
    mockMedia({ width: 1440 });
    const toggle = vi.fn();
    renderWithClient(<AppSidebar me={user} variant="rail" activeHref={null} onToggleCollapsed={toggle} />);
    const docs = screen.getByRole("button", { name: t("nav.documents") });
    expect(docs).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(docs);
    expect(screen.getByRole("menu", { name: t("nav.documents") })).toBeInTheDocument();
    expect(screen.getByRole("menuitemradio", { name: t("sidebarNav.all") })).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: t("shell.expandSidebar") }));
    expect(toggle).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: t("account.menu") })).toBeInTheDocument();
  });
});
