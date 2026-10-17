import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { VersionRow } from "../api";
import { VersionPicker } from "./VersionPicker";

const row = (version: number, over: Partial<VersionRow> = {}): VersionRow => ({
  version,
  size_bytes: 100,
  created_at: "2026-01-02T10:30:00Z",
  created_by: "u1",
  author: `Author ${version}`,
  author_email: null,
  is_current: false,
  ...over,
});

const versions = [row(1), row(2), row(3, { is_current: true })];

describe("VersionPicker", () => {
  it("an option names the version author and date", () => {
    render(<VersionPicker versions={versions} fromV={1} toV={3} onChange={() => {}} />);
    // TZ is pinned to UTC in vitest.config.ts, so the format is deterministic.
    expect(screen.getAllByText(/v1 · Jan 2, 2026, 10:30 AM · Author 1/).length).toBeGreaterThan(0);
  });

  it("the current version is marked", () => {
    render(<VersionPicker versions={versions} fromV={1} toV={3} onChange={() => {}} />);
    expect(screen.getAllByText(/v3 \(current\)/).length).toBeGreaterThan(0);
  });

  it("changing From passes the new pair and keeps To", () => {
    const onChange = vi.fn();
    render(<VersionPicker versions={versions} fromV={1} toV={3} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2" } });

    expect(onChange).toHaveBeenCalledWith({ fromV: 2, toV: 3 });
  });

  it("changing To passes the new pair and keeps From", () => {
    const onChange = vi.fn();
    render(<VersionPicker versions={versions} fromV={1} toV={3} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2" } });

    expect(onChange).toHaveBeenCalledWith({ fromV: 1, toV: 2 });
  });

  it("options are in ascending order regardless of input", () => {
    render(
      <VersionPicker versions={[row(3), row(1), row(2)]} fromV={1} toV={3} onChange={() => {}} />,
    );
    const opts = screen.getAllByRole("option").slice(0, 3);
    expect(opts.map((o) => (o as HTMLOptionElement).value)).toEqual(["1", "2", "3"]);
  });

  it("the `aside` slot renders an action next to the selects", () => {
    render(
      <VersionPicker
        versions={versions}
        fromV={1}
        toV={3}
        onChange={() => {}}
        aside={<button>Open full screen ↗</button>}
      />,
    );
    expect(screen.getByText("Open full screen ↗")).toBeInTheDocument();
  });

  it("a version without an author does not break the label", () => {
    render(
      <VersionPicker
        versions={[row(1, { author: null }), row(2)]}
        fromV={1}
        toV={2}
        onChange={() => {}}
      />,
    );
    expect(screen.getAllByText(/v1 · Jan 2, 2026, 10:30 AM$/).length).toBeGreaterThan(0);
  });
});
