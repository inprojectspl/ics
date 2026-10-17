import type { ReactElement } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { AssetSummary, ProjectSummary } from "../../api";
import { api } from "../../api";
import { t } from "../../lib/i18n";
import type { AssetFilter } from "../../lib/useAssetFilter";
import { renderWithClient } from "../../test-utils";
import { mockMedia } from "../../test-media";
import { ConfirmProvider } from "../ConfirmDialog";
import { ToastProvider } from "../Toast";
import { ActiveFilterChips, DocumentFilters } from "./DocumentFilters";
import { DocumentList } from "./DocumentList";
import { DocumentRow } from "./DocumentRow";
import { KIND_LABEL, KindIcon, kindIcon } from "./kindIcon";
import { SecurityStatusBadge, ShareStatus, shareState } from "./ShareStatus";

function mk(over: Partial<AssetSummary> = {}): AssetSummary {
  return {
    id: "a1",
    slug: "s1",
    title: "Rollout plan",
    kind: "md_single",
    size_bytes: 2048,
    version: 3,
    security_status: "clean",
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-29T10:00:00Z",
    ...over,
  };
}

const project: ProjectSummary = {
  id: "p1",
  slug: "alpha",
  name: "Alpha",
  description: null,
  created_by: null,
  created_at: "2026-09-01T00:00:00Z",
  my_role: "owner",
  member_count: 1,
  asset_count: 1,
};

function wrap(ui: ReactElement) {
  return renderWithClient(
    <ToastProvider>
      <ConfirmProvider>{ui}</ConfirmProvider>
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(api, "listDocTypes").mockResolvedValue([]);
  mockMedia({ width: 1440 });
});

describe("ShareStatus", () => {
  it("names the widest audience of the active links", () => {
    expect(shareState(undefined)).toBe("none");
    expect(shareState([])).toBe("none");
    expect(shareState(["org_sso", "public"])).toBe("public");
    expect(shareState(["password", "org_sso"])).toBe("password");
    expect(shareState(["magic_email"])).toBe("org");
  });

  it("shows a word and a title, security only when it needs attention", () => {
    const { rerender } = wrap(
      <>
        <ShareStatus modes={["public"]} />
        <SecurityStatusBadge status="critical" />
      </>,
    );
    expect(screen.getByText(t("shareStatus.public"))).toBeInTheDocument();
    expect(screen.getByText(t("securityBadge.critical"))).toBeInTheDocument();
    rerender(
      <>
        <SecurityStatusBadge status="warn" />
        <SecurityStatusBadge status="critical" bypassed />
        <SecurityStatusBadge status="clean" />
      </>,
    );
    expect(screen.getAllByText(t("securityBadge.warn"))).toHaveLength(1);
    expect(screen.queryByText(t("securityBadge.critical"))).not.toBeInTheDocument();
  });

  it("kindIcon gives every kind a glyph and a name", () => {
    for (const k of Object.keys(KIND_LABEL) as AssetSummary["kind"][]) expect(kindIcon(k)).toBeTruthy();
    const { container } = wrap(<KindIcon kind="pdf_doc" aria-hidden />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

describe("DocumentRow", () => {
  const actions = { onUpdate: vi.fn(), onVersions: vi.fn(), onProject: vi.fn(), onBinding: vi.fn(), onShare: vi.fn(), onDelete: vi.fn() };

  it("the title is the link to the document; metadata and the project are shown", () => {
    wrap(
      <ul>
        <DocumentRow
          asset={mk({ summary: "Short summary", project_id: "p1", has_binding: true, owner: { id: "u", email: "o@x", display_name: "Olivia" }, my_role: "editor" })}
          projectsById={new Map([["p1", project]])}
          onCommitRename={vi.fn()}
          onPinChanged={vi.fn()}
          actions={actions}
        />
      </ul>,
    );
    expect(screen.getByRole("link", { name: "Rollout plan" })).toHaveAttribute("href", "/v/s1");
    expect(screen.getByText("Short summary")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Alpha" })).toHaveAttribute("href", "/projects/alpha");
    expect(screen.getByText("GitLab")).toBeInTheDocument();
    expect(screen.getByText(/Olivia/)).toBeInTheDocument();
  });

  it("offers pin plus the shared asset actions in one menu, and renames inline", () => {
    const onCommitRename = vi.fn();
    wrap(
      <ul>
        <DocumentRow asset={mk({ version: 2 })} projectsById={new Map()} onCommitRename={onCommitRename} onPinChanged={vi.fn()} actions={actions} sortKey="created" />
      </ul>,
    );
    fireEvent.click(screen.getByRole("button", { name: t("documentRow.actions", { title: "Rollout plan" }) }));
    const menu = screen.getByRole("menu");
    const labels = within(menu).getAllByRole("menuitem").map((b) => b.textContent);
    expect(labels[0]).toBe(t("pinButton.add"));
    expect(labels).toEqual(expect.arrayContaining([t("assetMenu.rename"), t("common.share"), t("common.delete")]));
    fireEvent.click(within(menu).getByRole("menuitem", { name: t("common.share") }));
    expect(actions.onShare).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: t("documentRow.actions", { title: "Rollout plan" }) }));
    fireEvent.click(screen.getByRole("menuitem", { name: t("assetMenu.rename") }));
    const input = screen.getByRole("textbox", { name: t("assetToolbar.nameLabel") });
    fireEvent.change(input, { target: { value: "New title" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    expect(onCommitRename).toHaveBeenCalledWith("a1", "New title");
  });

  it("a reader gets no management actions", () => {
    wrap(
      <ul>
        <DocumentRow asset={mk({ my_role: "viewer" })} projectsById={new Map()} onCommitRename={vi.fn()} onPinChanged={vi.fn()} actions={actions} />
      </ul>,
    );
    fireEvent.click(screen.getByRole("button", { name: t("documentRow.actions", { title: "Rollout plan" }) }));
    expect(screen.queryByRole("menuitem", { name: t("common.delete") })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: t("assetMenu.rename") })).not.toBeInTheDocument();
  });

  it("the star pins through the API and reports the change", async () => {
    const pin = vi.spyOn(api, "pinAsset").mockResolvedValue({ id: "a1", pinned_at: "2026-09-30T00:00:00Z" });
    const onPinChanged = vi.fn();
    wrap(
      <ul>
        <DocumentRow asset={mk()} projectsById={new Map()} onCommitRename={vi.fn()} onPinChanged={onPinChanged} actions={actions} />
      </ul>,
    );
    const star = screen.getByRole("button", { name: t("pinButton.add") });
    expect(star).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(star);
    await waitFor(() => expect(onPinChanged).toHaveBeenCalledWith(true));
    expect(pin).toHaveBeenCalledWith("a1");
  });
});

describe("DocumentList", () => {
  it("keeps favourites in the given order, without a separate section", () => {
    wrap(
      <DocumentList
        assets={[mk({ id: "b", slug: "b", title: "Regular" }), mk({ id: "a", slug: "a", title: "Favourite", pinned_at: "2026-09-01T00:00:00Z" })]}
        projectsById={new Map()}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("Regular"),
      expect.stringContaining("Favourite"),
    ]);
  });

  it("renders no frame for an empty page", () => {
    wrap(<DocumentList assets={[]} projectsById={new Map()} onChanged={vi.fn()} />);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});

describe("DocumentFilters", () => {
  const counts = new Map<AssetFilter, number>([
    ["type:md_single", 4],
    ["type:pdf_doc", 2],
    ["state:public", 1],
    ["state:unshared", 5],
    ["project:p1", 3],
    ["project:p9", 1],
    ["tag:alpha", 2],
    ["tag:beta", 1],
    ["doctype:spec", 2],
    ["doctype:adr", 1],
    ["fresh:current", 3],
    ["fresh:review_overdue", 1],
  ]);

  it("gives a long group a search that ignores diacritics and keeps what is on in view", () => {
    const names = ["Café design", "Client portal", "FTTH rollout", "Onboarding", "Contracts", "Marketing", "Sales", "HR", "Purchasing"];
    const many = names.map((name, i) => ({ ...project, id: `p${i}`, name }));
    const projectCounts = new Map<AssetFilter, number>(many.map((p) => [`project:${p.id}` as AssetFilter, 1]));
    wrap(
      <DocumentFilters active={["project:p8"]} counts={projectCounts} onToggle={vi.fn()} onClear={vi.fn()} projects={many} kinds={["project"]} />,
    );
    fireEvent.click(screen.getByRole("button", { name: new RegExp(t("filters.title")) }));
    const panel = screen.getByRole("dialog", { name: t("filters.title") });
    // Capped until asked: the selected project plus the first few.
    expect(within(panel).getAllByRole("checkbox")).toHaveLength(6);
    expect(within(panel).getByRole("checkbox", { name: /Purchasing/ })).toBeChecked();
    fireEvent.change(within(panel).getByRole("searchbox", { name: t("filters.searchProject") }), { target: { value: "cafe" } });
    expect(within(panel).getAllByRole("checkbox").map((c) => c.closest("label")?.textContent)).toEqual([
      expect.stringContaining("Purchasing"),
      expect.stringContaining("Café design"),
    ]);
    fireEvent.change(within(panel).getByRole("searchbox", { name: t("filters.searchProject") }), { target: { value: "" } });
    fireEvent.click(within(panel).getByRole("button", { name: t("filters.showAll", { count: 9 }) }));
    expect(within(panel).getAllByRole("checkbox")).toHaveLength(9);
  });

  it("lists only groups with a real choice, with counts, and toggles values", () => {
    const onToggle = vi.fn();
    const onClear = vi.fn();
    wrap(
      <DocumentFilters
        active={["type:pdf_doc"]}
        counts={counts}
        onToggle={onToggle}
        onClear={onClear}
        projects={[project]}
        docTypeLabels={new Map([["spec", "Specification"]])}
      />,
    );
    const trigger = screen.getByRole("button", { name: new RegExp(t("filters.title")) });
    expect(trigger).toHaveTextContent("1");
    fireEvent.click(trigger);
    const panel = screen.getByRole("dialog", { name: t("filters.title") });
    expect(within(panel).getByRole("checkbox", { name: /PDF/ })).toBeChecked();
    expect(within(panel).getByText("Specification")).toBeInTheDocument();
    expect(within(panel).getByText(t("assetToolbar.hiddenProject"))).toBeInTheDocument();
    expect(within(panel).queryByText(t("sidebarNav.gitlab"))).not.toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("checkbox", { name: /#alpha/ }));
    expect(onToggle).toHaveBeenCalledWith("tag:alpha");
    fireEvent.click(within(panel).getByRole("button", { name: t("filters.clear") }));
    expect(onClear).toHaveBeenCalled();
    fireEvent.click(within(panel).getByRole("button", { name: t("filters.done") }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("hides itself when nothing could be filtered", () => {
    wrap(<DocumentFilters active={[]} counts={new Map()} onToggle={vi.fn()} onClear={vi.fn()} kinds={["source"]} />);
    expect(screen.queryByRole("button", { name: new RegExp(t("filters.title")) })).not.toBeInTheDocument();
  });

  it("chips name the active filters, remove one and clear all", () => {
    const onToggle = vi.fn();
    const onClear = vi.fn();
    wrap(
      <ActiveFilterChips
        active={["type:md_single", "project:p1", "tag:zzz"]}
        counts={counts}
        onToggle={onToggle}
        onClear={onClear}
        projects={[project]}
      />,
    );
    const group = screen.getByRole("group", { name: t("filters.active") });
    fireEvent.click(within(group).getByRole("button", { name: t("filters.remove", { name: "Alpha" }) }));
    expect(onToggle).toHaveBeenCalledWith("project:p1");
    // An active value with no documents left still gets its chip.
    expect(within(group).getByRole("button", { name: t("filters.remove", { name: "#zzz" }) })).toBeInTheDocument();
    fireEvent.click(within(group).getByRole("button", { name: t("filters.clear") }));
    expect(onClear).toHaveBeenCalled();
  });

  it("chips render nothing without active filters", () => {
    wrap(<ActiveFilterChips active={[]} counts={counts} onToggle={vi.fn()} onClear={vi.fn()} />);
    expect(screen.queryByRole("group", { name: t("filters.active") })).not.toBeInTheDocument();
  });
});
