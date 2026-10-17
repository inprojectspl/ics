import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, renderHook, screen, fireEvent, waitFor } from "@testing-library/react";
import type { AssetDoc, VersionRow } from "../api";
import { formatDateTime } from "./format";
import { useVersionPreview } from "./useVersionPreview";

const doc = (over: Partial<AssetDoc> = {}): AssetDoc => ({
  id: "a1",
  slug: "abc123",
  title: "Report",
  kind: "md_single",
  version: 3,
  size_bytes: 100,
  entry_path: "doc.md",
  html: "<p>x</p>",
  created_at: "2026-01-01T08:00:00Z",
  updated_at: "2026-03-04T08:15:00Z",
  current_version: 3,
  ...over,
});

const setup = (d: AssetDoc | null) =>
  renderHook(() =>
    useVersionPreview({
      doc: d,
      basePath: "/v/abc123",
      loadVersions: () => Promise.resolve([]),
      downloadPath: "/api/assets/by-slug/abc123/download",
    }),
  );

describe("useVersionPreview", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/v/abc123");
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("current version: no preview, no notice, download available", () => {
    const { result } = setup(doc());
    expect(result.current.previewVersion).toBeNull();
    expect(result.current.staleNotice).toBeNull();
    expect(result.current.downloadHref).toBe("/api/assets/by-slug/abc123/download");
    expect(result.current.meta).toContain("March 4, 2026");
  });

  it("archived preview: shows the notice and hides the download (the ZIP would be the current version)", () => {
    const { result } = setup(
      doc({ preview_version: 1, version: 1, version_created_at: "2026-01-02T10:30:00Z" }),
    );
    expect(result.current.previewVersion).toBe(1);
    expect(result.current.downloadHref).toBeUndefined();
    render(<>{result.current.staleNotice}</>);
    expect(screen.getByRole("alert")).toHaveTextContent("v1");
    expect(screen.getByRole("alert")).toHaveTextContent("v3");
  });

  it("dates the overline by the version being read, not the last document change", () => {
    const { result } = setup(
      doc({ preview_version: 1, version: 1, version_created_at: "2026-01-02T10:30:00Z" }),
    );
    expect(result.current.meta).toContain("January 2, 2026");
    expect(result.current.meta).not.toContain("March");
  });

  it("dates the current version in the notice like the version list, not by updated_at", async () => {
    const rows = [
      { version: 3, created_at: "2026-03-04T08:14:10Z", is_current: true },
      { version: 1, created_at: "2026-01-02T10:30:00Z", is_current: false },
    ] as VersionRow[];
    function Notice() {
      return useVersionPreview({
        doc: doc({ preview_version: 1, version: 1, version_created_at: "2026-01-02T10:30:00Z", updated_at: "2026-03-04T08:15:30Z" }),
        basePath: "/v/abc123",
        loadVersions: () => Promise.resolve(rows),
        downloadPath: "/api/assets/by-slug/abc123/download",
      }).staleNotice;
    }
    render(<Notice />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(formatDateTime("2026-03-04T08:14:10Z") ?? "-"),
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent(formatDateTime("2026-03-04T08:15:30Z") ?? "-");
  });

  it("goToVersion adds ?ver= for an archived version and clears it for the current one", () => {
    const { result } = setup(doc({ preview_version: 1, version: 1 }));

    result.current.goToVersion(2);
    expect(window.location.pathname + window.location.search).toBe("/v/abc123?ver=2");

    result.current.goToVersion(3); // 3 == current_version
    expect(window.location.pathname + window.location.search).toBe("/v/abc123");
  });

  it("'Back to current' in the notice leads to the URL without ?ver=", () => {
    window.history.replaceState({}, "", "/v/abc123?ver=1");
    const { result } = setup(doc({ preview_version: 1, version: 1 }));
    render(<>{result.current.staleNotice}</>);

    fireEvent.click(screen.getByText("Back to current"));

    expect(window.location.pathname + window.location.search).toBe("/v/abc123");
  });

  it("does not crash without a doc (still loading)", () => {
    const { result } = setup(null);
    expect(result.current.previewVersion).toBeNull();
    expect(result.current.meta).toBeNull();
    expect(result.current.staleNotice).toBeNull();
  });
});
