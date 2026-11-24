// Shared by the Google Sheets tab tests: the app, its link and a preview as
// the API returns them, a fetch stub routed by method and path, the page.
import { vi } from "vitest";

import { renderWithClient } from "../../test-utils";
import { ConfirmProvider } from "../ConfirmDialog";
import { MicroAppPage } from "./MicroAppPage";

export const RIGHTS = { use: true, publish: false, control: true, manage_access: true, prepare: false };

export function app(rights: Partial<typeof RIGHTS> = {}) {
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

export const MAPPING = {
  id: "m1",
  collection: "requests",
  tabs: [{ sheet_id: 0, title: "Requests" }],
  key_field: null as string | null,
  tab_field: null as string | null,
  columns: [
    { field: "title", header: "Title", owner: "both" },
    { field: "status", header: "Status", owner: "sheet" },
  ],
  read_only: false,
};

export const LINK = {
  spreadsheet_id: "1AbCdEfGhIjKlMnOpQrStUvWxYz",
  spreadsheet_url: "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit",
  mappings: [MAPPING],
  account_mode: "per_user",
  revision: 4,
  paused: false,
  auto_sync: false,
  auto_checked_at: null,
  auto_error: null,
};

export function sheets(over: Record<string, unknown> = {}) {
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

export const PREVIEW = {
  id: "op1",
  state: "previewed",
  google_status: "none",
  error: null,
  mine: true,
  auto: false,
  created_at: "2026-11-22T10:00:00Z",
  summary: { imports: 1, exports: 0, conflicts: 2, creates: 0, appends: 0, issues: 1 },
  result: null,
  headers: { requests: { title: "Title", status: "Status" } },
  updates: [
    {
      collection: "requests",
      tab: "Requests",
      record_id: "r1",
      row: 2,
      import: { status: "done" },
      export: {},
      conflicts: [{ field: "title", base: "Old", app: "App title", sheet: "Sheet title" }],
    },
    {
      collection: "requests",
      tab: "Requests",
      record_id: "r2",
      row: 3,
      import: {},
      export: {},
      conflicts: [{ field: "title", base: null, app: "Mine", sheet: "Theirs" }],
    },
  ],
  creates: [],
  appends: [],
  issues: [{ kind: "duplicate_key", collection: "requests", tab: "Requests", row: 5, first_row: 2, first_tab: "Requests" }],
};

/** A JSON reply with a status; plain values are answered with 200. */
export class Reply {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {}
}

type Route = (url: string, init?: RequestInit) => unknown;

export function mockFetch(routes: Record<string, Route | unknown>) {
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

export const sent = (m: ReturnType<typeof mockFetch>, method: string, path: string) =>
  m.mock.calls.filter(([u, i]) => (i?.method ?? "GET") === method && u.split("?")[0] === path);
export const bodyOf = (m: ReturnType<typeof mockFetch>, method: string, path: string, n = 0) =>
  JSON.parse(String(sent(m, method, path)[n]?.[1]?.body));

export const S = "/api/micro-applications/a1/sheets";

export function renderPage(search = "?tab=sheets") {
  window.history.replaceState({}, "", `/v/s1${search}`);
  return renderWithClient(
    <ConfirmProvider>
      <MicroAppPage assetId="a1" title="Requests" base="/v/s1" />
    </ConfirmProvider>,
  );
}
