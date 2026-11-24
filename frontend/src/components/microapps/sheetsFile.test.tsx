import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

import { setLocale } from "../../lib/i18n";
import { LINK, MAPPING, PREVIEW, Reply, S, app, mockFetch, renderPage, sent, sheets } from "./sheetsFixtures";

describe("Google Sheets tab, a file with several collections and tabs", () => {
  beforeEach(() => setLocale("en", { persist: false }));
  afterEach(() => vi.unstubAllGlobals());

  const FILE = {
    ...LINK,
    mappings: [
      {
        ...MAPPING,
        id: "m2",
        collection: "orders",
        tabs: [
          { sheet_id: 11, title: "Orders 2026-10" },
          { sheet_id: 12, title: "Orders 2026-11", append: true },
        ],
        key_field: "number",
        tab_field: "month",
        columns: [{ field: "number", header: "Number", owner: "both" }],
      },
      { ...MAPPING, id: "m3", collection: "customers", tabs: [{ sheet_id: 13, title: "Customers" }], read_only: true },
    ],
  };

  it("shows each collection with its tabs, where new records go and what the app only reads", async () => {
    mockFetch({ "GET /api/micro-applications/a1": app(), [`GET ${S}`]: sheets({ link: FILE }) });
    renderPage();
    expect(await screen.findByText("Collection orders")).toBeInTheDocument();
    expect(screen.getByText(/^Tabs: Orders 2026-10, Orders 2026-11/)).toBeInTheDocument();
    expect(screen.getByText("New records go to Orders 2026-11.")).toBeInTheDocument();
    expect(screen.getByText("Name of the row's tab")).toBeInTheDocument();
    expect(screen.getByText("The app only reads these tabs: every column is the sheet's.")).toBeInTheDocument();
  });

  it("names the collection, tab and row of every change", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ link: FILE }),
      [`POST ${S}/preview`]: {
        ...PREVIEW,
        summary: { imports: 2, exports: 1, conflicts: 0, creates: 1, appends: 1, issues: 1 },
        headers: { orders: { number: "Number" }, customers: { code: "Code" } },
        updates: [{ collection: "orders", tab: "Orders 2026-11", row: 4, record_id: "r1", import: { month: "Orders 2026-11" }, export: {}, conflicts: [] }],
        creates: [{ collection: "customers", tab: "Customers", row: 3, record_id: "r2", data: { code: "ACME" } }],
        appends: [{ collection: "orders", tab: "Orders 2026-11", record_id: "r3", values: { number: "C-9" } }],
        issues: [{ kind: "duplicate_key", collection: "orders", tab: "Orders 2026-11", row: 5, first_row: 2, first_tab: "Orders 2026-10" }],
      },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    expect(await screen.findByText("orders · Orders 2026-11, row 4")).toBeInTheDocument();
    expect(screen.getByText("customers · Customers, row 3: Code: ACME")).toBeInTheDocument();
    expect(screen.getByText("orders · Orders 2026-11: Number: C-9")).toBeInTheDocument();
    expect(
      screen.getByText("orders · Orders 2026-11: Row 5: the same ID as in tab Orders 2026-10, row 2; the row is skipped."),
    ).toBeInTheDocument();
  });

  it("names the tab whose headers stop the sync", async () => {
    mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ link: FILE }),
      [`POST ${S}/preview`]: new Reply(409, { detail: "x", code: "sheet_headers_missing", missing: ["Status"], tab: "Orders 2026-11" }),
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Preview" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Tab: Orders 2026-11");
    expect(alert).toHaveTextContent("Missing columns: Status");
  });

  it("offers to check a sheet write left pending, the one blocking the next sync", async () => {
    const pending = { ...PREVIEW, state: "applied", google_status: "pending", unsettled: true, result: { app_changes: 2 } };
    const m = mockFetch({
      "GET /api/micro-applications/a1": app(),
      [`GET ${S}`]: sheets({ link: FILE, operations: [pending] }),
      [`POST ${S}/operations/op1/check`]: { ...pending, google_status: "failed", error: "google_not_applied" },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Check result" }));
    await waitFor(() => expect(sent(m, "POST", `${S}/operations/op1/check`)).toHaveLength(1));
  });
});
