import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { AssetSummary, DiffSummary, VersionRow } from "../api";
import { setLocale } from "../lib/i18n";
import { ConfirmProvider } from "./ConfirmDialog";
import { VersionsDialog } from "./VersionsDialog";

const listVersions = vi.fn();
const diffVersions = vi.fn();
const navigate = vi.fn();

vi.mock("../lib/navigate", () => ({ navigate: (to: string) => navigate(to) }));
vi.mock("../api", () => ({
  api: {
    listVersions: (...a: unknown[]) => listVersions(...a),
    diffVersions: (...a: unknown[]) => diffVersions(...a),
    restoreVersion: vi.fn(),
  },
}));

const row = (version: number, is_current = false): VersionRow => ({
  version,
  size_bytes: 10,
  created_at: "2026-11-16T10:00:00Z",
  created_by: null,
  author: "Alice",
  author_email: null,
  is_current,
});

const asset = (over: Partial<AssetSummary> = {}): AssetSummary =>
  ({ id: "a1", slug: "app", title: "Rejestr", kind: "md_single", version: 2, my_role: "owner", ...over }) as AssetSummary;

function open(a: AssetSummary) {
  return render(
    <ConfirmProvider>
      <VersionsDialog asset={a} onClose={() => {}} onRestored={() => {}} />
    </ConfirmProvider>,
  );
}

beforeEach(() => {
  setLocale("en", { persist: false });
  listVersions.mockResolvedValue([row(2, true), row(1)]);
  diffVersions.mockResolvedValue({
    kind: "micro_application",
    from_version: 1,
    to_version: 2,
    from_meta: row(1),
    to_meta: row(2, true),
    files: [{ path: "microapp.json", change: "modified", binary: false, added_lines: 2, removed_lines: 0, size_from: 1, size_to: 2 }],
    app_changes: [{ area: "role", name: "reviewer", change: "changed", detail: "+requests.export" }],
  } satisfies DiffSummary);
});

describe("VersionsDialog", () => {
  it("offers preview and restore for a document", async () => {
    open(asset());
    expect(await screen.findByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View" })).toBeInTheDocument();
  });

  it("lets a micro-application's history be read and compared, not previewed or restored", async () => {
    listVersions.mockResolvedValue([{ ...row(2), release_status: "failed" }, { ...row(1, true), release_status: "active" }]);
    open(asset({ kind: "micro_application" }));
    expect(await screen.findByText("publication failed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare with previous" }));
    expect(navigate).toHaveBeenCalledWith("/v/app/diff?from=1&to=2");
    expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();
    expect(screen.queryByRole("button", { name: "View" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    const changes = await screen.findByRole("region", { name: "Changes in the app" });
    expect(changes).toHaveTextContent("reviewer");
    expect(changes).toHaveTextContent("+requests.export");
    expect(screen.getByText("microapp.json")).toBeInTheDocument();
  });
});
