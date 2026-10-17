import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { VersionRow } from "../api";
import { setLocale } from "../lib/i18n";
import { VersionHistorySection } from "./VersionHistorySection";

const row = (version: number, is_current = false): VersionRow => ({
  version,
  size_bytes: 1024,
  created_at: "2026-01-02T10:30:00Z",
  created_by: "u1",
  author: "Author",
  author_email: null,
  is_current,
});

describe("VersionHistorySection", () => {
  it("shows the version count while collapsed", async () => {
    const load = vi.fn().mockResolvedValue([row(3, true), row(2), row(1)]);
    render(<VersionHistorySection load={load} onPreview={() => {}} />);
    expect(await screen.findByText("Version history · 3 versions")).toBeInTheDocument();
    // The list loads only on expand; the section starts collapsed.
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("pluralises the version count in Polish", async () => {
    setLocale("pl", { persist: false });
    render(
      <VersionHistorySection load={() => Promise.resolve([row(1, true)])} onPreview={() => {}} />,
    );
    expect(await screen.findByText("Historia wersji · 1 wersja")).toBeInTheDocument();
  });

  it("expanding shows the list with a \"View version\" action", async () => {
    const onPreview = vi.fn();
    render(
      <VersionHistorySection
        load={() => Promise.resolve([row(2, true), row(1)])}
        onPreview={onPreview}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { expanded: false }));
    fireEvent.click(await screen.findByText("View version"));
    expect(onPreview).toHaveBeenCalledWith(1);
  });

  it("the current version has an \"Open current\" action", async () => {
    const onPreview = vi.fn();
    render(
      <VersionHistorySection
        load={() => Promise.resolve([row(2, true), row(1)])}
        onPreview={onPreview}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { expanded: false }));
    fireEvent.click(await screen.findByText("Open current"));
    expect(onPreview).toHaveBeenCalledWith(2);
  });

  it("the version being viewed gets no action", async () => {
    render(
      <VersionHistorySection
        load={() => Promise.resolve([row(2, true), row(1)])}
        onPreview={() => {}}
        activeVersion={1}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { expanded: false }));
    expect(await screen.findByText("Viewing")).toBeInTheDocument();
    expect(screen.queryByText("View version")).not.toBeInTheDocument();
  });

  it("no history means no section (assets created before versioning)", async () => {
    const { container } = render(
      <VersionHistorySection load={() => Promise.resolve([])} onPreview={() => {}} />,
    );
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("a fetch error hides the section: it is an extra, not document content", async () => {
    const { container } = render(
      <VersionHistorySection
        load={() => Promise.reject(new Error("500 boom"))}
        onPreview={() => {}}
      />,
    );
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders in English with English plurals", async () => {
    setLocale("en", { persist: false });
    render(
      <VersionHistorySection
        load={() => Promise.resolve([row(2, true), row(1)])}
        onPreview={() => {}}
      />,
    );
    expect(await screen.findByText("Version history · 2 versions")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(await screen.findByRole("button", { name: "View version" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open current" })).toBeInTheDocument();
    expect(screen.getByText("Current")).toBeInTheDocument();
  });
});
