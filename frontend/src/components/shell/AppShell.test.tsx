import { useEffect, useRef } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import type { AssetSummary, Me, ProjectSummary } from "../../api";
import { api } from "../../api";
import { getLocale, t } from "../../lib/i18n";
import * as nav from "../../lib/navigate";
import * as theme from "../../lib/theme";
import { renderWithClient } from "../../test-utils";
import { mockMedia } from "../../test-media";
import { AccountMenu } from "./AccountMenu";
import { AppShell } from "./AppShell";
import { CommandPalette } from "./CommandPalette";
import { useShell } from "./shellContext";

vi.mock("./NotificationsButton", () => ({ NotificationsButton: () => <span>bell</span> }));

const me: Me = { id: "u1", email: "alice@example.com", display_name: "Alice Smith", role: "user", dev_stub_sso: false, locale: null };

const page = <T,>(items: T[]) => ({ items, total: items.length, page: 1, page_size: 200 });

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  window.history.replaceState({}, "", "/");
  localStorage.clear();
  vi.spyOn(api, "listProjects").mockResolvedValue(
    page([
      {
        id: "p1",
        slug: "alpha",
        name: "Alpha",
        description: null,
        created_by: null,
        created_at: "2026-09-01T00:00:00Z",
        my_role: "owner",
        member_count: 1,
        asset_count: 2,
      } satisfies ProjectSummary,
    ]) as Awaited<ReturnType<typeof api.listProjects>>,
  );
  vi.spyOn(api, "myQuota").mockResolvedValue({ used_bytes: 1, quota_bytes: 100 });
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});

let mounts = 0;
function Counter() {
  const seen = useRef(false);
  useEffect(() => {
    if (!seen.current) {
      seen.current = true;
      mounts += 1;
    }
  }, []);
  return <p>page</p>;
}

/** A page with a focus switch, like the reader and the graph explorer. */
function FocusPage() {
  const { focusMode, setFocusMode } = useShell();
  return (
    <button type="button" aria-pressed={focusMode} onClick={() => setFocusMode(!focusMode)}>
      focus
    </button>
  );
}

describe("AppShell", () => {
  it("leaves focus mode with Escape, but not while the command palette takes it", () => {
    mockMedia({ width: 1440 });
    renderWithClient(
      <AppShell me={me}>
        <FocusPage />
      </AppShell>,
    );
    const toggle = screen.getByRole("button", { name: "focus" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");

    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-pressed", "true");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });

  it("offers a skip link to the main region and one navigation", () => {
    mockMedia({ width: 1440 });
    renderWithClient(
      <AppShell me={me}>
        <p>content</p>
      </AppShell>,
    );
    expect(screen.getByRole("link", { name: t("shell.skipToContent") })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    expect(screen.getAllByRole("navigation", { name: t("nav.label") })).toHaveLength(1);
  });

  it("Cmd/Ctrl+K opens and closes the command palette", () => {
    mockMedia({ width: 1440 });
    renderWithClient(
      <AppShell me={me}>
        <p>content</p>
      </AppShell>,
    );
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    expect(screen.getByRole("dialog", { name: t("palette.title") })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "K", ctrlKey: true });
    expect(screen.queryByRole("dialog", { name: t("palette.title") })).not.toBeInTheDocument();
  });

  it("on a phone the navigation is a drawer that closes after a pick", async () => {
    mockMedia({ width: 390 });
    renderWithClient(
      <AppShell me={me}>
        <p>content</p>
      </AppShell>,
    );
    expect(screen.queryByRole("navigation", { name: t("nav.label") })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("shell.openNav") }));
    const drawer = screen.getByRole("dialog", { name: t("nav.label") });
    expect(drawer).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: t("nav.allProjects") }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: t("nav.label") })).not.toBeInTheDocument());
    expect(window.location.pathname).toBe("/projects");
  });

  it("a session arriving late wraps the same mounted page", () => {
    mockMedia({ width: 1440 });
    mounts = 0;
    const { rerender } = renderWithClient(
      <AppShell me={null}>
        <Counter />
      </AppShell>,
    );
    expect(screen.getByRole("button", { name: t("shell.viewSettings") })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: t("nav.label") })).not.toBeInTheDocument();
    rerender(
      <AppShell me={me}>
        <Counter />
      </AppShell>,
    );
    expect(screen.getByRole("navigation", { name: t("nav.label") })).toBeInTheDocument();
    expect(mounts).toBe(1);
  });
});

const asset = (over: Partial<AssetSummary>) =>
  ({ id: "a1", slug: "a1", title: "Rollout plan", kind: "md_single", summary: "brief", ...over }) as AssetSummary;

describe("CommandPalette", () => {
  it("searches documents from two characters and opens the highlighted one", async () => {
    const search = vi.spyOn(api, "searchAssets").mockResolvedValue([asset({}), asset({ id: "a2", slug: "a2", title: "Plan B" })]);
    const go = vi.spyOn(nav, "navigate").mockImplementation(() => {});
    const onClose = vi.fn();
    renderWithClient(<CommandPalette me={me} open onClose={onClose} />);
    const input = screen.getByRole("combobox", { name: t("palette.title") });
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "p" } });
    expect(search).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "plan" } });
    expect(await screen.findByRole("option", { name: /Rollout plan/ })).toBeInTheDocument();
    expect(search).toHaveBeenCalledWith("plan", 6, undefined, expect.any(AbortSignal));
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: /Plan B/ })).toHaveAttribute("aria-selected", "true");
    expect(input.getAttribute("aria-activedescendant")).toBe(screen.getByRole("option", { name: /Plan B/ }).id);
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onClose).toHaveBeenCalled();
    expect(go).toHaveBeenCalledWith("/v/a1");
  });

  it("lists projects, places and actions without a query, and filters them", async () => {
    const go = vi.spyOn(nav, "navigate").mockImplementation(() => {});
    renderWithClient(<CommandPalette me={me} open onClose={vi.fn()} />);
    expect(await screen.findByRole("option", { name: "Alpha" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: t("nav.admin") })).not.toBeInTheDocument();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: t("palette.newProject").toLowerCase() } });
    fireEvent.click(await screen.findByRole("option", { name: t("palette.newProject") }));
    expect(go).toHaveBeenCalledWith("/projects?new=1");
  });

  it("switches the theme from the palette and says when nothing matches", async () => {
    vi.spyOn(api, "searchAssets").mockResolvedValue([]);
    theme.setThemePreference("light");
    renderWithClient(<CommandPalette me={{ ...me, role: "admin" }} open onClose={vi.fn()} />);
    expect(screen.getByRole("option", { name: t("nav.admin") })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: t("theme.toDark") }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    theme.setThemePreference("light");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "zzzzqq" } });
    await waitFor(() => expect(screen.getByText(t("palette.empty"))).toBeInTheDocument());
  });

  it("Escape closes it", () => {
    const onClose = vi.fn();
    renderWithClient(<CommandPalette me={me} open onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("renders nothing while closed", () => {
    renderWithClient(<CommandPalette me={me} open={false} onClose={vi.fn()} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("AccountMenu", () => {
  it("shows who is signed in, sets theme and language, and signs out", async () => {
    mockMedia({ width: 1440 });
    const saveLocale = vi.spyOn(api, "setMyLocale").mockResolvedValue(me);
    const logout = vi.spyOn(api, "logout").mockResolvedValue({ ok: true });
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, assign } as Location);
    renderWithClient(<AccountMenu me={me} />);
    const signOut = t("common.signOut");
    fireEvent.click(screen.getByRole("button", { name: t("userMenu.open") }));
    expect(screen.getByText("Alice Smith")).toBeInTheDocument();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: t("theme.dark") }));
    expect(localStorage.getItem("ics-theme")).toBe("dark");
    expect(screen.getByRole("radio", { name: t("theme.dark") })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("radio", { name: t("theme.system") }));
    expect(localStorage.getItem("ics-theme")).toBe("system");
    act(() => {
      fireEvent.click(screen.getByRole("radio", { name: t("language.en") }));
    });
    expect(getLocale()).toBe("en");
    expect(saveLocale).toHaveBeenCalledWith("en");
    fireEvent.click(await screen.findByRole("button", { name: signOut }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
    expect(logout).toHaveBeenCalled();
  });

  it("a dev stub session has no sign out", () => {
    mockMedia({ width: 1440 });
    renderWithClient(<AccountMenu me={{ ...me, dev_stub_sso: true, display_name: null }} />);
    fireEvent.click(screen.getByRole("button", { name: t("userMenu.open") }));
    expect(screen.queryByRole("button", { name: t("common.signOut") })).not.toBeInTheDocument();
    expect(screen.getByText(/dev-stub/)).toBeInTheDocument();
  });
});
