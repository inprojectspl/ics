import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { setLocale } from "../../lib/i18n";
import { renderWithClient } from "../../test-utils";
import { ConfirmProvider } from "../ConfirmDialog";
import { MicroAppPage } from "./MicroAppPage";

function app(over: Record<string, unknown> = {}) {
  return {
    asset_id: "a1", slug: "s1", title: "Rejestr wniosków", description: null, environment: "prod",
    app_url: "https://k7m2q9x4.apps.example/", owner: { id: "u", display_name: "Alice" }, project: null,
    desired_state: "enabled", generation: 3, package_version: 2,
    active_release: { id: "r1", package_version: 2, digest: "sha256:abcdef0123456789", activated_at: null, schema: [1, 1] },
    last_publication: null,
    runtime: { state: "sleeping", sampled_at: null, fresh: false, inflight: 0, queued: 0, open_connections: 0, last_used_at: null, last_error: null, breaker_open_until: null },
    data: { measured: true, sampled_at: null, bytes: 16384, rows_estimate: 3, tables: 1, schema_version: 1 },
    rights: { use: true, publish: true, control: true, manage_access: true, prepare: true },
    suspended_at: null,
    ...over,
  };
}

const access = {
  asset_id: "a1",
  title: "Rejestr wniosków",
  app_url: "https://k7m2q9x4.apps.example/",
  roles: [
    { role: "employee", label: "Employee", description: "Files own requests.", permissions: ["requests.read", "requests.write"] },
    { role: "reviewer", label: "Reviewer", description: null, permissions: ["requests.approve"] },
  ],
  permissions: [
    { permission: "requests.approve", label: "Approve requests", description: null, platform: false, allows: ["POST /approve"] },
    { permission: "requests.read", label: "Read own requests", description: null, platform: false, allows: ["requests: read"] },
    { permission: "requests.write", label: "File requests", description: null, platform: false, allows: ["requests: create"] },
    { permission: "app.control", label: null, description: null, platform: true, allows: ["enable, suspend"] },
  ],
  people: [
    { email: "alice@example.com", display_name: "Alice", can_open: true, access: "owner", roles: [], permissions: [], effective_permissions: [] },
    {
      email: "bob@example.com",
      display_name: "Bob",
      can_open: true,
      access: "viewer",
      roles: [],
      permissions: ["requests.read"],
      effective_permissions: ["requests.read"],
    },
  ],
  projects: [],
};

type Route = (url: string, init?: RequestInit) => unknown;

function mockFetch(routes: Record<string, Route | unknown>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0] ?? url;
    const key = `${init?.method ?? "GET"} ${path}`;
    const hit = routes[key];
    if (hit === undefined) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    const body = typeof hit === "function" ? (hit as Route)(url, init) : hit;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const calls = (m: ReturnType<typeof mockFetch>, method: string) => m.mock.calls.filter(([, i]) => (i?.method ?? "GET") === method);

function renderPage(tab?: string) {
  window.history.replaceState({}, "", `/v/s1${tab ? `?tab=${tab}` : ""}`);
  return renderWithClient(
    <ConfirmProvider>
      <MicroAppPage assetId="a1" title="Rejestr wniosków" base="/v/s1" />
    </ConfirmProvider>,
  );
}

beforeEach(() => setLocale("en", { persist: false }));
afterEach(() => vi.unstubAllGlobals());

describe("MicroAppPage, App tab", () => {
  it("shows desired and runtime state, data and the way into the app", async () => {
    mockFetch({ "GET /api/micro-applications/a1": app() });
    renderPage();
    expect(await screen.findByText("Enabled")).toBeInTheDocument();
    expect(screen.getByText("Sleeping: no resources")).toBeInTheDocument();
    expect(screen.getByText("Active release: package v2")).toBeInTheDocument();
    expect(screen.getByText("≈3 rows in 1 table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open/ })).toHaveAttribute("href", "https://k7m2q9x4.apps.example/");
    expect(screen.getByRole("button", { name: "Put to sleep" })).toBeInTheDocument();
    for (const name of ["App", "Data", "Access", "Logs"]) expect(screen.getByRole("link", { name })).toBeInTheDocument();
  });

  it("hides the controls, Access and Logs without the rights", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app({ rights: { use: true, publish: false, control: false, manage_access: false, prepare: false } }),
    });
    renderPage();
    expect(await screen.findByText("Enabled")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Put to sleep|Restart|Suspend|Enable/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "Access" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Logs" })).toBeNull();
  });

  it("falls back to the App tab when the requested one is not allowed", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app({ rights: { use: true, publish: false, control: false, manage_access: false, prepare: false } }),
    });
    renderPage("access");
    expect(await screen.findByText("Enabled")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "App" })).toHaveAttribute("aria-current", "page");
  });

  it("offers Enable for a suspended app and sends the generation with an idempotency key", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app({ desired_state: "suspended" }),
      "POST /api/micro-applications/a1/control": { operation_id: "op_1", status: "succeeded", terminal: true },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Enable" }));
    await waitFor(() => expect(calls(fetchMock, "POST")).toHaveLength(1));
    const [url, init] = calls(fetchMock, "POST")[0]!;
    expect(url).toBe("/api/micro-applications/a1/control");
    const body = JSON.parse(String(init!.body));
    expect(body).toMatchObject({ action: "enable", expected_generation: 3 });
    expect(body.idempotency_key).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Open/ })).toBeNull();
  });
});

describe("MicroAppPage, Data tab", () => {
  it("renders the document HTML and loads more of one collection with its cursor", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app(),
      "GET /api/micro-applications/a1/document": (url: string) =>
        url.includes("collection=")
          ? {
              asset_id: "a1", title: "R", markdown: "### requests (continued)", html: "<h3>requests (continued)</h3><p>row 51</p>",
              collections: [{ name: "requests", readable: true, next_cursor: null }], error: null,
            }
          : {
              asset_id: "a1", title: "R", markdown: "## requests", html: "<h2>requests</h2><p>row 1</p>",
              collections: [{ name: "requests", readable: true, next_cursor: "c50" }, { name: "notes", readable: true, next_cursor: null }],
              error: null,
            },
    });
    renderPage("data");
    expect(await screen.findByText("row 1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more of notes" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show more of requests" }));
    expect(await screen.findByText("row 51")).toBeInTheDocument();
    const more = fetchMock.mock.calls.map(([u]) => u).find((u) => u.includes("collection="));
    expect(new URL(more!, "http://x").searchParams.get("collection")).toBe("requests");
    expect(new URL(more!, "http://x").searchParams.get("cursor")).toBe("c50");
    // The last page has no cursor: the button goes away.
    await waitFor(() => expect(screen.queryByRole("button", { name: "Show more of requests" })).toBeNull());
  });
});

describe("MicroAppPage, Access tab", () => {
  it("gives a person a role and keeps their single permissions", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app(),
      "GET /api/micro-applications/a1/access": access,
      "PUT /api/micro-applications/a1/access": { added: [], removed: [], roles_added: ["reviewer"], roles_removed: [], open_change: null },
    });
    renderPage("access");
    const row = (await screen.findByText("Bob")).closest("li")!;
    const roles = within(row).getByRole("group", { name: "Roles of Bob" });
    fireEvent.click(within(roles).getByRole("checkbox", { name: "Reviewer" }));
    fireEvent.click(within(row).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls(fetchMock, "PUT")).toHaveLength(1));
    expect(JSON.parse(String(calls(fetchMock, "PUT")[0]![1]!.body))).toEqual({
      user_email: "bob@example.com",
      roles: ["reviewer"],
      permissions: ["requests.read"],
      can_open: true,
    });
  });

  it("shows a permission a chosen role gives as given, not as a second choice", async () => {
    mockFetch({ "GET /api/micro-applications/a1": app(), "GET /api/micro-applications/a1/access": access });
    renderPage("access");
    const row = (await screen.findByText("Alice")).closest("li")!;
    fireEvent.click(within(row).getByRole("checkbox", { name: "Employee" }));
    fireEvent.click(within(row).getByRole("button", { name: "Single permissions" }));
    const write = within(row).getByRole("checkbox", { name: /requests\.write/ });
    expect(write).toBeChecked();
    expect(write).toBeDisabled();
    expect(within(row).getAllByText("(from role Employee)")).toHaveLength(2);
    // Labels from the manifest name the permission; the code stays beside it.
    expect(within(row).getByRole("checkbox", { name: /Approve requests/ })).not.toBeChecked();
    expect(screen.getByRole("heading", { name: "Roles in this app" })).toBeInTheDocument();
    // Platform permissions stand apart, under ICS's own name.
    const platform = within(row).getByRole("group", { name: "Co-author and operator: Alice" });
    expect(within(platform).getByRole("checkbox", { name: /Control: enable, sleep, restart, logs/ })).not.toBeChecked();
    expect(screen.getByText(/the same roles, whatever their role in the project/)).toBeInTheDocument();
  });

  it("saves a person's exact permission set", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app(),
      "GET /api/micro-applications/a1/access": access,
      "PUT /api/micro-applications/a1/access": { added: ["requests.write"], removed: [], open_change: null },
    });
    renderPage("access");
    const row = (await screen.findByText("Bob")).closest("li")!;
    fireEvent.click(within(row).getByRole("checkbox", { name: /requests\.write/ }));
    fireEvent.click(within(row).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls(fetchMock, "PUT")).toHaveLength(1));
    const [url, init] = calls(fetchMock, "PUT")[0]!;
    expect(url).toBe("/api/micro-applications/a1/access");
    expect(JSON.parse(String(init!.body))).toEqual({
      user_email: "bob@example.com",
      roles: [],
      permissions: ["requests.read", "requests.write"],
      can_open: true,
    });
  });

  it("removes a person and says when they still open the app another way", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app(),
      "GET /api/micro-applications/a1/access": access,
      "PUT /api/micro-applications/a1/access": { added: [], removed: ["requests.read"], open_change: null, still_opens_via: "editor" },
    });
    renderPage("access");
    const row = (await screen.findByText("Bob")).closest("li")!;
    expect(within(screen.getByText("Alice").closest("li")!).queryByRole("button", { name: "Remove" })).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: "Remove" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(calls(fetchMock, "PUT")).toHaveLength(1));
    expect(JSON.parse(String(calls(fetchMock, "PUT")[0]![1]!.body))).toEqual({
      user_email: "bob@example.com",
      roles: [],
      permissions: [],
      can_open: false,
    });
    expect(await screen.findByText(/bob@example.com can still open the app \(editor\)/)).toBeInTheDocument();
  });

  it("adds a person by e-mail in the chosen role", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app(),
      "GET /api/micro-applications/a1/access": access,
      "PUT /api/micro-applications/a1/access": { added: ["requests.read"], removed: [], open_change: "viewer_share_added" },
    });
    renderPage("access");
    fireEvent.click(await screen.findByRole("button", { name: "Add a person" }));
    const form = screen.getByRole("form", { name: "Add a person" });
    fireEvent.change(within(form).getByRole("textbox", { name: "Email" }), { target: { value: " carol@example.com " } });
    fireEvent.click(within(form).getByRole("checkbox", { name: "Employee" }));
    fireEvent.click(within(form).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(calls(fetchMock, "PUT")).toHaveLength(1));
    expect(JSON.parse(String(calls(fetchMock, "PUT")[0]![1]!.body))).toEqual({
      user_email: "carol@example.com",
      roles: ["employee"],
      permissions: [],
      can_open: true,
    });
  });
});
