import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { setLocale } from "../lib/i18n";
import { StaleVersionNotice } from "./StaleVersionNotice";

describe("StaleVersionNotice", () => {
  it("shows the viewed and the current version", () => {
    render(<StaleVersionNotice previewVersion={2} currentVersion={5} onBackToCurrent={() => {}} />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("v2");
    expect(alert).toHaveTextContent("v5");
    expect(alert).toHaveTextContent(/outdated/i);
  });

  it("adds the dates when given", () => {
    render(
      <StaleVersionNotice
        previewVersion={1}
        currentVersion={3}
        versionCreatedAt="2026-01-02T10:30:00Z"
        currentCreatedAt="2026-03-04T08:15:00Z"
        onBackToCurrent={() => {}}
      />,
    );
    // TZ=UTC is pinned in vitest.config.ts, so the format is deterministic.
    expect(screen.getByRole("alert")).toHaveTextContent("Jan 2, 2026");
    expect(screen.getByRole("alert")).toHaveTextContent("Mar 4, 2026");
  });

  it("ignores an invalid date instead of rendering Invalid Date", () => {
    render(
      <StaleVersionNotice
        previewVersion={1}
        currentVersion={2}
        versionCreatedAt="not-a-date"
        onBackToCurrent={() => {}}
      />,
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent(/invalid/i);
  });

  it("\"Back to current\" calls the callback", () => {
    const onBack = vi.fn();
    render(<StaleVersionNotice previewVersion={2} currentVersion={5} onBackToCurrent={onBack} />);
    fireEvent.click(screen.getByText("Back to current"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("does not float over the sticky chrome", () => {
    // A z-index of its own would scroll the bar over the ICS navbar
    // (`ViewerChrome` is `z-20`). The bar is plain in-flow content: no
    // `fixed`/`sticky` and no z-index.
    render(<StaleVersionNotice previewVersion={2} currentVersion={5} onBackToCurrent={() => {}} />);
    const cls = screen.getByRole("alert").className;
    expect(cls).not.toMatch(/\bfixed\b|\bsticky\b/);
    expect(cls).not.toMatch(/\bz-\d/);
  });

  it("the close button hides the bar", () => {
    render(<StaleVersionNotice previewVersion={2} currentVersion={5} onBackToCurrent={() => {}} />);
    fireEvent.click(screen.getByLabelText("Hide version warning"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders in English with English dates", () => {
    setLocale("en", { persist: false });
    render(
      <StaleVersionNotice
        previewVersion={2}
        currentVersion={5}
        versionCreatedAt="2026-01-02T10:00:00Z"
        currentCreatedAt="2026-03-04T10:00:00Z"
        onBackToCurrent={() => {}}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/Outdated version \(v2, Jan 2, 2026/);
    expect(alert).toHaveTextContent(/Current version: v5 \(Mar 4, 2026/);
    expect(screen.getByRole("button", { name: "Back to current" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide version warning" })).toBeInTheDocument();
  });
});
