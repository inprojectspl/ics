import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ArchivedBanner } from "./ArchivedBanner";

describe("ArchivedBanner", () => {
  it("says since when the document is archived and offers the way back to its managers", () => {
    const onUnarchive = vi.fn();
    render(<ArchivedBanner archivedAt="2026-11-02T10:00:00Z" onUnarchive={onUnarchive} />);
    expect(screen.getByRole("status")).toHaveTextContent(/in the archive since/);
    fireEvent.click(screen.getByRole("button", { name: "Restore from archive" }));
    expect(onUnarchive).toHaveBeenCalled();
  });

  it("has no button for a reader who cannot manage the document", () => {
    render(<ArchivedBanner archivedAt="2026-11-02T10:00:00Z" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
