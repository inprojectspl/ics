import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { setLocale } from "../../lib/i18n";
import { renderWithClient } from "../../test-utils";
import { ConfirmProvider } from "../ConfirmDialog";
import { MicroAppPage } from "./MicroAppPage";

const RIGHTS = { use: true, publish: false, control: true, manage_access: true, prepare: false };

function app(rights: Partial<typeof RIGHTS> = {}) {
  return {
    asset_id: "a1", slug: "s1", title: "Requests", description: null, environment: "prod",
    app_url: "https://k7m2q9x4.apps.example/", owner: { id: "u", display_name: "Alice" }, project: null,
    desired_state: "enabled", generation: 3, package_version: 2,
    active_release: { id: "r1", package_version: 2, digest: "sha256:abcdef0123456789", activated_at: null, schema: [1, 1] },
    last_publication: null,
    runtime: { state: "sleeping", sampled_at: null, fresh: false, inflight: 0, queued: 0, open_connections: 0, last_used_at: null, last_error: null, breaker_open_until: null, realtime: { sockets: 0, people: 0 } },
    data: { measured: true, sampled_at: null, bytes: 16384, rows_estimate: 3, tables: 1, schema_version: 1 },
    rights: { ...RIGHTS, ...rights },
    suspended_at: null,
  };
}

const LINK = {
  collection: "requests",
  spreadsheet_id: "1AbCdEfGhIjKlMnOpQrStUvWxYz",
  spreadsheet_url: "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit",
  sheet_title: "Requests",
  key_field: null,
  columns: [
    { field: "title", header: "Title", owner: "both" },
    { field: "status", header: "Status", owner: "sheet" },
  ],
  account_mode: "per_user",
  revision: 4,
  paused: false,
  auto_sync: false,
  auto_checked_at: null,
  auto_error: null,
};

function sheets(over: Record<string, unknown> = {}) {
  return {
    enabled: true,
    rights: { configure: true, run: true, owner: false },
    my_google: { email: "bob@gmail.com" },
    link: LINK,
    row_limit: 5000,
    auto_interval_seconds: 120,
    operations: [],
    ...over,
  };
}

const PREVIEW = {
  id: "op1",
  state: "previewed",
  google_status: "none",
  error: null,
  mine: true,
  auto: false,
  created_at: "2026-11-22T10:00:00Z",
  summary: { imports: 1, exports: 0, conflicts: 2, creates: 0, appends: 0, issues: 1 },
  result: null,
  headers: { title: "Title", status: "Status" },
  updates: [
    {
      record_id: "r1",
      row: 2,
      import: { status: "done" },
      export: {},
      conflicts: [{ field: "title", base: "Old", app: "App title", sheet: "Sheet title" }],
    },
    {
      record_id: "r2",
      row: 3,
      import: {},
      export: {},
      conflicts: [{ field: "title", base: null, app: "Mine", sheet: "Theirs" }],
    },
  ],
  creates: [],
  appends: [],
  issues: [{ kind: "duplicate_key", row: 5, first_row: 2 }],
};

/** A JSON reply with a status; plain values are answered with 200. */
class Reply {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {}
}

type Route = (url: string, init?: RequestInit) => unknown;

function mockFetch(routes: Record<string, Route | unknown>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0] ?? url;
    const hit = routes[`${init?.method ?? "GET"} ${path}`];
    if (hit === undefined) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    const body = typeof hit === "function" ? (hit as Route)(url, init) : hit;
    if (body instanceof Reply) return new Response(JSON.stringify(body.body), { status: body.status });
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const sent = (m: ReturnType<typeof mockFetch>, method: string, path: string) =>
  m.mock.calls.filter(([u, i]) => (i?.method ?? "GET") === method && u.split("?")[0] === path);
const bodyOf = (m: ReturnType<typeof mockFetch>, method: string, path: string, n = 0) =>
  JSON.parse(String(sent(m, method, path)[n]?.[1]?.body));

const S = "/api/micro-applications/a1/sheets";

function renderPage(search = "?tab=sheets") {
  window.history.replaceState({}, "", `/v/s1${search}`);
  return renderWithClient(
    <ConfirmProvider>
      <MicroAppPage assetId="a1" title="Requests" base="/v/s1" />
    </ConfirmProvider>,
  );
}

beforeEach(() => setLocale("en", { persist: false }));
afterEach(() => vi.unstubAllGlobals());

describe("Google Sheets tab, visibility", () => {
  it.each([
    ["control", { control: true, manage_access: false }],
    ["manage_access", { control: false, manage_access: true }],
  ])("is shown with %s", async (_name, rights) => {
    mockFetch({ "GET /api/micro-applications/a1": app(rights), [`GET ${S}`]: sheets() });
    renderPage("");
    expect(await screen.findByRole("link", { name: "Google Sheets" })).toHaveAttribute("href", "/v/s1?tab=sheets");
  });

  it("is hidden without control and manage_access, and its address falls back to the App tab", async () => {
    mockFetch({ "GET /api/micro-applications/a1": app({ control: false, manage_access: false }) });
    renderPage();
    expect(await screen.findByRole("link", { name: "App" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: "Google Sheets" })).toBeNull();
  });
});

describe("Google Sheets tab, my Google account", () => {
  it("links the connect button to the consent start, coming back to this tab", async () => {
    mockFetch({ "GET /api/micro-applications/a1": app(), [`GET ${S}`]: sheets({ my_google: null }) });
    renderPage();
    const connect = await screen.findByRole("link", { name: "Connect Google account" });
    expect(connect).toHaveAttribute("href", `/api/integrations/google/connect?next=${encodeURIComponent("/v/s1?tab=sheets")}`);
  });

  it("says the account is connected on return and drops the parameter from the address", async () => {
    mockFetch({ "GET /api/micro-applications/a1": app(), [`GET ${S}`]: sheets() });
    renderPage("?tab=sheets&google=connected");
    expect(await screen.findByText("Google account connected.")).toBeInTheDocument();
    expect(screen.getByText("Connected as bob@gmail.com")).toBeInTheDocument();
    await waitFor(() => expect(window.location.search).toBe("?tab=sheets"));
  });

  it("explains a failed connection by its code", async () => {
    mockFetch({ "GET /api/micro-applications/a1": app(), [`GET ${S}`]: sheets({ my_google: null }) });
    renderPage("?tab=sheets&google=google_scope_missing");
    expect(await screen.findByRole("alert")).toHaveTextContent("Google did not grant access to Sheets");
  });

  it("disconnects after confirmation", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets(),
      "DELETE /api/integrations/google": { disconnected: true },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(sent(fetchMock, "DELETE", "/api/integrations/google")).toHaveLength(1));
  });
});

describe("Google Sheets tab, the link", () => {
  it("offers no form without a link and says an AI agent sets it up", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ link: null, my_google: null }),
    });
    renderPage();
    expect(await screen.findByText("This app is not linked to a sheet.")).toBeInTheDocument();
    expect(screen.getByText(/set up by an AI agent through ics-mcp/)).toHaveTextContent("build a new app from a spreadsheet");
    expect(screen.queryByRole("form")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    // The agent reads the sheet with my account: connecting is offered here as well.
    expect(screen.getByText("The agent reads the spreadsheet with your Google account, so connect it first.")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Connect Google account" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();
  });

  it("tells someone who cannot manage the app who sets the link up", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app({ manage_access: false }),
      [`GET ${S}`]: sheets({ link: null, rights: { configure: false, run: true, owner: false } }),
    });
    renderPage();
    expect(await screen.findByText(/at the request of someone who manages this app/)).toBeInTheDocument();
    expect(screen.queryByText(/Ask your agent/)).toBeNull();
  });

  it("shows the link read-only, with the key field and the owner's row limit", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ link: { ...LINK, key_field: "title", account_mode: "owner_account" }, row_limit: 2500 }),
    });
    renderPage();
    const open = await screen.findByRole("link", { name: "Open in Google Sheets" });
    expect(open).toHaveAttribute("href", LINK.spreadsheet_url);
    expect(screen.getByText("requests")).toBeInTheDocument();
    expect(screen.getByText(": Edited in the sheet")).toBeInTheDocument();
    expect(screen.getByText("By the Title column (title): its values are unique in the sheet.")).toBeInTheDocument();
    expect(screen.getByText("The owner's account")).toBeInTheDocument();
    expect(screen.getByText("2,500 rows")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit/ })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("says rows are matched by content without a key field", async () => {
    mockFetch({ "GET /api/micro-applications/a1": app(), [`GET ${S}`]: sheets() });
    renderPage();
    expect(await screen.findByText(/^By content:/)).toBeInTheDocument();
    expect(screen.getByText("5,000 rows")).toBeInTheDocument();
    expect(screen.getByText("On demand")).toBeInTheDocument();
  });

  it("says the link syncs by itself, when it last looked at the sheet and that conflicts wait", async () => {
    const checked = new Date(Date.now() - 5 * 60_000).toISOString();
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ link: { ...LINK, auto_sync: true, auto_checked_at: checked, auto_error: "conflicts" }, auto_interval_seconds: 300, auto_active_interval_seconds: 20 }),
    });
    renderPage();
    expect(await screen.findByText("Syncs by itself while the app is in use: app changes at once, the sheet every 20 s while the app is open and every 5 min while it is only awake. A sleeping app does not sync.")).toBeInTheDocument();
    expect(screen.getByText("Sheet last checked: 5 minutes ago")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Automatic sync is waiting: there are conflicts to decide, run a preview.");
    expect(screen.queryByText("On demand")).toBeNull();
  });

  it("explains by its code why the automatic sync stopped", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ link: { ...LINK, auto_sync: true, auto_error: "google_no_access" } }),
    });
    renderPage();
    expect(await screen.findByText("Syncs by itself while the app is in use: app changes at once, the sheet every 30 s while the app is open and every 2 min while it is only awake. A sleeping app does not sync.")).toBeInTheDocument();
    expect(screen.queryByText(/^Sheet last checked/)).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Automatic sync stopped: The Google account cannot open this spreadsheet.");
  });

  it("removes the link after confirmation", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets(),
      [`DELETE ${S}`]: null,
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Remove link" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove link" }));
    await waitFor(() => expect(sent(fetchMock, "DELETE", S)).toHaveLength(1));
  });

  it("offers no removal without the right to manage the app", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app({ manage_access: false }),
      [`GET ${S}`]: sheets({ rights: { configure: false, run: true, owner: false } }),
    });
    renderPage();
    expect(await screen.findByRole("button", { name: "Preview" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove link" })).toBeNull();
  });
});

describe("Google Sheets tab, the sync", () => {
  it("offers no Apply when nothing differs, only remembering an agreed state", async () => {
    const empty = { ...PREVIEW, updates: [], issues: [], summary: { imports: 0, exports: 0, conflicts: 0, creates: 0, appends: 0, issues: 0, agreed: 0 } };
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ operations: [empty] }),
    });
    renderPage();
    expect(await screen.findByText("Nothing to change: the app and the sheet agree.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remember the agreed state" })).toBeNull();
  });

  it("offers to remember values both sides already share", async () => {
    const agreed = { ...PREVIEW, updates: [], issues: [], summary: { imports: 0, exports: 0, conflicts: 0, creates: 0, appends: 0, issues: 0, agreed: 2 } };
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ operations: [agreed] }),
    });
    renderPage();
    expect(await screen.findByRole("button", { name: "Remember the agreed state" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  });

  it("marks syncs made by the automatic sync in the history", async () => {
    const byAuto = { id: "op2", state: "applied", google_status: "confirmed", error: null, mine: false, auto: true, created_at: "2026-11-22T11:00:00Z", summary: {}, result: null };
    const byMe = { ...PREVIEW, state: "applied", google_status: "confirmed", result: { app_changes: 1 } };
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ operations: [byAuto, byMe] }),
    });
    renderPage();
    const items = within(await screen.findByRole("list", { name: "Recent syncs" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("automatic");
    expect(items[0]).not.toHaveTextContent("(yours)");
    expect(items[1]).toHaveTextContent("(yours)");
    expect(items[1]).not.toHaveTextContent("automatic");
  });

  it("previews, needs every conflict decided, then applies with the decisions", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets(),
      [`POST ${S}/preview`]: PREVIEW,
      [`POST ${S}/operations/op1/apply`]: {
        ...PREVIEW,
        state: "applied",
        google_status: "confirmed",
        result: { app_changes: 2, replayed: false },
      },
    });
    renderPage();
    expect(await screen.findByText(/never repeats it by itself/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    // Business terms: header names, not field ids.
    const changes = await screen.findByRole("list", { name: "Changes per record" });
    expect(within(changes).getByText("Status: done")).toBeInTheDocument();
    expect(within(changes).getAllByRole("group", { name: "Title: changed in the app and in the sheet" })).toHaveLength(2);
    expect(screen.getByText("Row 5: the same ID as row 2; the row is skipped.")).toBeInTheDocument();

    const apply = screen.getByRole("button", { name: "Apply" });
    expect(apply).toBeDisabled();
    expect(screen.getByText("Conflicts to decide: 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Keep the app value: App title" }));
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Take the sheet value: Theirs" }));
    expect(apply).toBeEnabled();
    fireEvent.click(apply);

    await waitFor(() => expect(sent(fetchMock, "POST", `${S}/operations/op1/apply`)).toHaveLength(1));
    expect(bodyOf(fetchMock, "POST", `${S}/operations/op1/apply`)).toEqual({ decisions: { "r1:title": "app", "r2:title": "sheet" } });
    expect(await screen.findByText("Changes saved in the app: 2.")).toBeInTheDocument();
    expect(screen.getByText("The sheet is updated.")).toBeInTheDocument();
  });

  it("offers Check result when Google did not confirm the write, and never repeats it itself", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets(),
      [`POST ${S}/preview`]: { ...PREVIEW, summary: { imports: 1 }, updates: [{ ...PREVIEW.updates[0], conflicts: [] }], issues: [] },
      [`POST ${S}/operations/op1/apply`]: { ...PREVIEW, state: "applied", google_status: "uncertain", result: { app_changes: 1 } },
      [`POST ${S}/operations/op1/check`]: { ...PREVIEW, state: "applied", google_status: "confirmed", result: { app_changes: 1 } },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    fireEvent.click(await screen.findByRole("button", { name: "Apply" }));
    expect(await screen.findByText(/Google did not confirm the write/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check result" }));
    expect(await screen.findByText("The sheet is updated.")).toBeInTheDocument();
    expect(sent(fetchMock, "POST", `${S}/operations/op1/check`)).toHaveLength(1);
    expect(sent(fetchMock, "POST", `${S}/operations/op1/apply`)).toHaveLength(1);
  });

  it("resumes my unconfirmed write after a reload", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ operations: [{ ...PREVIEW, state: "applied", google_status: "uncertain", result: { app_changes: 1 } }] }),
    });
    renderPage();
    expect(await screen.findByRole("button", { name: "Check result" })).toBeInTheDocument();
    const history = screen.getByRole("list", { name: "Recent syncs" });
    expect(within(history).getByText("Sheet: unconfirmed")).toBeInTheDocument();
  });

  it("asks the owner for access when the Google account cannot open the sheet", async () => {
    const fetchMock = mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets(),
      [`POST ${S}/preview`]: new Reply(409, { detail: "x", code: "google_no_access", action: "request_access" }),
      [`POST ${S}/request-access`]: { sent: true },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    expect(await screen.findByText("The Google account cannot open this spreadsheet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask the owner for access" }));
    expect(await screen.findByText(/The owner got your request/)).toBeInTheDocument();
    expect(sent(fetchMock, "POST", `${S}/request-access`)).toHaveLength(1);
  });

  it("offers to connect Google when the sync needs it", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ my_google: null }),
      [`POST ${S}/preview`]: new Reply(409, { detail: "x", code: "google_not_connected", action: "connect_google" }),
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Connect your Google account first.");
    expect(within(alert).getByRole("link", { name: "Connect Google account" })).toHaveAttribute(
      "href",
      `/api/integrations/google/connect?next=${encodeURIComponent("/v/s1?tab=sheets")}`,
    );
  });

  it("hides the sync from someone who only configures", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app({ control: false }),
      [`GET ${S}`]: sheets({ rights: { configure: true, run: false, owner: false } }),
    });
    renderPage();
    expect(await screen.findByRole("button", { name: "Remove link" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();
  });

  it("names rows of records missing from the app and rows matching no record", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets(),
      [`POST ${S}/preview`]: {
        ...PREVIEW,
        issues: [
          { kind: "record_not_in_app", row: 7, record_id: "r9" },
          { kind: "unmatched_row", row: 8 },
        ],
      },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    expect(await screen.findByText("Row 7: its record was deleted in the app or you cannot see it; the row is skipped.")).toBeInTheDocument();
    expect(screen.getByText(/^Row 8: only the columns edited in the app are filled/)).toBeInTheDocument();
  });

  it("gives the app owner's row limit when the sheet is too large", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets(),
      [`POST ${S}/preview`]: new Reply(413, { detail: "x", code: "sheet_too_large", limit: 5000 }),
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The sheet tab has more rows than the app owner's limit allows.");
    expect(alert).toHaveTextContent("The app owner's limit is 5,000 rows.");
  });
});
