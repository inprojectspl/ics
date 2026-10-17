import { Suspense } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

import type { ContextPack, Me } from "../api";
import { t, tn } from "../lib/i18n";
import { readParams } from "./taskAgent/params";
import { TaskAgentViewLazy } from "./taskAgent/lazy";
import { TaskAgentView } from "./TaskAgentView";
import { renderWithClient as render } from "../test-utils";

// The frame reads the project from the list; kept apart from the fetch
// mock, so the `/api/context` calls are the only requests counted.
const listProjects = vi.fn();
vi.mock("../api", async (orig) => {
  const mod = await orig<typeof import("../api")>();
  return { ...mod, api: { ...mod.api, listProjects: (...a: unknown[]) => listProjects(...a) } };
});
vi.mock("../lib/useDocTypes", () => ({
  useDocTypes: () => [],
  useDocTypeLabels: () => new Map([["spec", "Specification"]]),
}));

const me = { id: "u1", email: "a@example.com", display_name: null, role: "user" } as Me;


function pack(over: Partial<ContextPack> = {}): ContextPack {
  return {
    project: { slug: "p1", name: "Apollo", external: "apollo" },
    task: { system: "openproject", wp: "4711", ancestors: [] },
    doc_types: { spec: "Treat as the binding contract." },
    documents: [
      {
        slug: "spec1",
        title: "Payment spec",
        summary: "How payments work.",
        doc_type: "spec",
        version: 3,
        flags: ["basis_changed"],
        required: true,
        via: [
          { kind: "direct", role: "context", required: true },
          { kind: "inherited", wp: "4700", role: "context", required: false },
        ],
        estimated_tokens: 1200,
      },
      {
        slug: "adr2",
        title: "ADR 2",
        version: 1,
        freshness: "review_overdue",
        via: [{ kind: "neighbour", from: "spec1", type: "basis_for" }],
        has_outline: false,
      },
      {
        slug: "old1",
        title: "Old spec",
        freshness: "superseded",
        collapsed: true,
        superseded_by: "spec1",
        required: true,
      },
    ],
    edges: [
      ["adr2", "contradicts", "spec1", { target_anchor: "why", changed: [2, 3] }],
      ["spec1", "depends_on", "adr2"],
    ],
    warnings: [
      { code: "contradicts", params: { from: "adr2", to: "spec1" } },
      { code: "superseded", params: { slug: "old1", successor: "spec1", required: true } },
      { code: "superseded", params: { slug: "old2", successor: "spec1", required: false } },
      { code: "basis_changed", params: { slug: "spec1" } },
      { code: "project_unmapped", params: { project: "apollo" } },
      { code: "task_unlinked", params: { system: "openproject", wp: "4711" } },
    ],
    truncated: { documents: 1, neighbours: 4, needed_tokens: 5200, max_budget_tokens: 4000, seed: "spec1" },
    estimated_tokens: 1650,
    hidden_count: 2,
    ...over,
  };
}

const fetchMock = vi.fn();

function reply(body: unknown, status = 200) {
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}

/** Query params of the n-th `/api/context` request. */
function sentParams(n = 0): URLSearchParams {
  const url = String(fetchMock.mock.calls[n]?.[0]);
  expect(url.startsWith("/api/context?")).toBe(true);
  return new URL(url, "http://x").searchParams;
}

function open(search: string) {
  window.history.replaceState({}, "", `/projects/p1/agent${search}`);
  render(<TaskAgentView me={me} slug="p1" />);
}

beforeEach(() => {
  listProjects.mockReset().mockResolvedValue({
    items: [{ id: "p", slug: "p1", name: "Apollo", description: null, created_by: "u1", created_at: "2026-01-01T00:00:00Z", my_role: "editor", member_count: 2, asset_count: 3 }],
    total: 1,
    page: 1,
    page_size: 200,
  });
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("TaskAgentView", () => {
  it("loads lazily: Suspense fallback first, then the view", async () => {
    reply(pack());
    window.history.replaceState({}, "", "/projects/p1/agent?wp=4711");
    render(
      <Suspense fallback={<p>lazy-fallback</p>}>
        <TaskAgentViewLazy me={me} slug="p1" />
      </Suspense>,
    );
    expect(screen.getByText("lazy-fallback")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Apollo" })).toBeInTheDocument();
    expect(await screen.findByText("Payment spec")).toBeInTheDocument();
  });

  it("sends the params from the URL to /api/context", async () => {
    reply(pack());
    open(
      "?wp=n-7&system=project_standard&ancestors=4700,4650&project=apollo-op&depth=2&budget=3200&include=references",
    );
    await screen.findByText("Payment spec");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const q = sentParams();
    expect(q.get("wp")).toBe("n-7");
    expect(q.get("system")).toBe("project_standard");
    expect(q.get("ancestors")).toBe("4700,4650");
    expect(q.get("project")).toBe("apollo-op");
    expect(q.get("depth")).toBe("2");
    expect(q.get("budget_tokens")).toBe("3200");
    expect(q.getAll("include")).toEqual(["references"]);
  });

  it("defaults the project to the one in view and sends the default depth and budget", async () => {
    reply(pack());
    open("?wp=4711&depth=9&budget=abc");
    await screen.findByText("Payment spec");
    const q = sentParams();
    expect(q.get("project")).toBe("p1");
    expect(q.get("depth")).toBe("1");
    expect(q.get("budget_tokens")).toBe("1800");
    expect(q.has("ancestors")).toBe(false);
  });

  it("shows warnings, truncation and why each document is there", async () => {
    reply(pack());
    open("?wp=4711");
    expect(
      await screen.findByText(t("taskAgent.warningContradicts", { from: "adr2", to: "spec1" })),
    ).toBeInTheDocument();
    for (const text of [
      t("taskAgent.warnings"),
      t("taskAgent.warningSupersededRequired", { slug: "old1", successor: "spec1" }),
      t("taskAgent.warningSuperseded", { slug: "old2", successor: "spec1" }),
      t("taskAgent.warningBasisChanged", { slug: "spec1" }),
      t("taskAgent.warningProjectUnmapped", { project: "apollo" }),
      t("taskAgent.warningTaskUnlinked", { wp: "4711" }),
      t("taskAgent.packCostValue", { used: 1650, budget: 1800 }),
    ]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    const cut = screen.getByRole("status");
    expect(cut).toHaveTextContent(t("taskAgent.truncated", { documents: 1, neighbours: 4 }));
    expect(cut).toHaveTextContent(t("taskAgent.truncatedNeighbourhood", { needed: 5200, max: 4000, seed: "spec1" }));
    expect(screen.getByText(tn("taskAgent.hidden", 2))).toBeInTheDocument();

    // Pack order is the reading order, numbered.
    expect(within(screen.getByText("Old spec").closest("li") as HTMLElement).getByText("3.")).toBeInTheDocument();
    const role = t("taskLinks.roleContext");
    expect(screen.getByText(t("taskAgent.viaDirect", { role }))).toBeInTheDocument();
    expect(screen.getByText(t("taskAgent.viaInherited", { role, wp: "4700" }))).toBeInTheDocument();
    expect(
      screen.getByText(t("taskAgent.viaNeighbour", { relation: t("relation.basisFor"), slug: "spec1" })),
    ).toBeInTheDocument();
    expect(screen.getByText(t("taskAgent.collapsed", { slug: "spec1" }))).toBeInTheDocument();
    expect(screen.getByText("Specification")).toBeInTheDocument();
    expect(screen.getByText(t("taskAgent.flagBasisChanged"))).toBeInTheDocument();
    // Once on the row, once as the cost of reading everything.
    expect(screen.getAllByText(tn("taskAgent.readCost", 1200))).toHaveLength(2);
    expect(screen.getByText(t("relations.basisChanged", { from: 2, to: 3 }))).toBeInTheDocument();
    // Compact edges: extras only where set.
    expect(screen.getByText("spec1#why")).toBeInTheDocument();
    expect(screen.getByText(t("taskAgent.noOutline"))).toBeInTheDocument();
  });

  it.each([
    [{ needed_tokens: 2600, seed: null }, () => t("taskAgent.truncatedRaise", { budget: 2600 })],
    [{ needed_tokens: 5200, seed: null }, () => t("taskAgent.truncatedNarrow", { needed: 5200, max: 4000 })],
  ])("tells how to get what the budget cut (%o)", async (over, expected) => {
    const base = pack().truncated;
    if (!base) throw new Error("fixture has a truncation");
    reply(pack({ truncated: { ...base, ...over } }));
    open("?wp=4711");
    expect(await screen.findByRole("status")).toHaveTextContent(expected());
  });

  it("hides the warning and truncation boxes when the pack has none", async () => {
    reply(pack({ warnings: [], truncated: null, hidden_count: undefined, project: null, documents: [], edges: [] }));
    open("?wp=4711");
    expect(await screen.findByText(t("taskAgent.empty"))).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(t("taskAgent.warnings"))).not.toBeInTheDocument();
    expect(screen.getByText(t("taskAgent.noProject"))).toBeInTheDocument();
  });

  it("writes a submitted form to the URL and asks again", async () => {
    reply(pack());
    open("?wp=4711");
    await screen.findByText("Payment spec");
    fireEvent.change(screen.getByLabelText(new RegExp(t("taskAgent.ancestors"))), {
      target: { value: "4700 4650" },
    });
    fireEvent.change(screen.getByLabelText(new RegExp(t("taskAgent.budget"))), {
      target: { value: "4000" },
    });
    fireEvent.click(screen.getByLabelText(t("taskAgent.includeDeliverables")));
    fireEvent.click(screen.getByRole("button", { name: t("taskAgent.submit") }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const q = sentParams(1);
    expect(q.get("ancestors")).toBe("4700,4650");
    expect(q.get("budget_tokens")).toBe("4000");
    expect(q.getAll("include")).toEqual(["deliverables"]);
    expect(window.location.pathname).toBe("/projects/p1/agent");
    expect(new URLSearchParams(window.location.search).get("budget")).toBe("4000");
    expect(new URLSearchParams(window.location.search).get("include")).toBe("deliverables");
  });

  it("asks nothing without a task and shows an API error", async () => {
    open("");
    expect(screen.getByText(t("taskAgent.start"))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    cleanup();

    reply({ detail: "too many context requests", code: "rate_limited" }, 429);
    open("?wp=4711");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

describe("readParams", () => {
  it("keeps only known include values and splits lists", () => {
    const p = readParams(new URLSearchParams("wp= 1 &include=references,bogus&ancestors=a,,b"), "p1");
    expect(p).toMatchObject({ wp: "1", include: ["references"], ancestors: ["a", "b"], project: "p1" });
  });
});
