import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { AssetDoc, SupersededBy } from "../api";
import { useVersionPreview } from "../lib/useVersionPreview";
import { SupersededBanner } from "./SupersededBanner";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("../lib/navigate", async (orig) => ({ ...(await orig<typeof import("../lib/navigate")>()), navigate }));

const successor: SupersededBy = {
  id: "s1",
  slug: "new",
  title: "Specification v3",
  since: "2026-03-04T08:15:00Z",
  href: "/s/tok123",
};

function doc(extra: Partial<AssetDoc>): AssetDoc {
  return {
    slug: "old",
    title: "Specification v2",
    kind: "md_single",
    version: 2,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    ...extra,
  } as AssetDoc;
}

const noVersions = () => Promise.resolve([]);

/** The share view renders whatever `useVersionPreview` puts in `staleNotice`. */
function ShareBanner({ d }: { d: AssetDoc }) {
  const { staleNotice } = useVersionPreview({
    doc: d,
    basePath: "/s/tok",
    loadVersions: noVersions,
    downloadPath: "/api/share/tok/download",
  });
  return <div>{staleNotice}</div>;
}

describe("SupersededBanner", () => {
  beforeEach(() => navigate.mockReset());

  it("shows no bar in the share view without access to the successor", () => {
    // The backend sends superseded_by only when the guest can open the successor.
    render(<ShareBanner d={doc({ superseded_by: null })} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the bar in the share view when the successor is accessible", () => {
    render(<ShareBanner d={doc({ superseded_by: successor })} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Specification v3");
    expect(alert).toHaveTextContent("March 4, 2026");
  });

  it("a click opens the successor", () => {
    render(<SupersededBanner successor={successor} />);
    const link = screen.getByRole("link", { name: "Open the current document" });
    expect(link).toHaveAttribute("href", "/s/tok123");
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledWith("/s/tok123");
  });

  it("a Ctrl-click leaves opening to the browser", () => {
    render(<SupersededBanner successor={successor} />);
    fireEvent.click(screen.getByRole("link"), { ctrlKey: true });
    expect(navigate).not.toHaveBeenCalled();
  });

  it("without a date and title uses the fallback wording and can be hidden", () => {
    render(<SupersededBanner successor={{ ...successor, title: null, since: null }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("an untitled document");
    fireEvent.click(screen.getByRole("button", { name: "Hide the replacement notice" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
