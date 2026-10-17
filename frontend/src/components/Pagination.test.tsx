import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Pagination } from "./Pagination";
import { setLocale, t } from "../lib/i18n";

describe("Pagination", () => {
  it("renders nothing when everything fits on one page", () => {
    const { container } = render(
      <Pagination page={1} pageSize={10} total={5} onPage={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the item range and the page number", () => {
    render(<Pagination page={2} pageSize={10} total={45} onPage={() => {}} />);
    expect(screen.getByText(t("homePagination.range", { start: 11, end: 20, total: 45 }))).toBeInTheDocument();
    expect(screen.getByText(t("pagination.pageOf", { page: 2, pageCount: 5 }))).toBeInTheDocument();
  });

  it("the last page ends the range at the total", () => {
    render(<Pagination page={5} pageSize={10} total={45} onPage={() => {}} />);
    expect(screen.getByText(t("homePagination.range", { start: 41, end: 45, total: 45 }))).toBeInTheDocument();
  });

  it("'Previous' is disabled on the first page", () => {
    render(<Pagination page={1} pageSize={10} total={50} onPage={() => {}} />);
    const prev = screen.getByRole("button", { name: /Previous/ });
    expect(prev).toBeDisabled();
  });

  it("'Next' is disabled on the last page", () => {
    render(<Pagination page={5} pageSize={10} total={50} onPage={() => {}} />);
    const next = screen.getByRole("button", { name: /Next/ });
    expect(next).toBeDisabled();
  });

  it("clicking 'Next' calls onPage with page+1", () => {
    const onPage = vi.fn();
    render(<Pagination page={2} pageSize={10} total={50} onPage={onPage} />);
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(onPage).toHaveBeenCalledWith(3);
  });

  it("clicking 'Previous' calls onPage with page-1", () => {
    const onPage = vi.fn();
    render(<Pagination page={3} pageSize={10} total={50} onPage={onPage} />);
    fireEvent.click(screen.getByRole("button", { name: /Previous/ }));
    expect(onPage).toHaveBeenCalledWith(2);
  });

  it("rounds pageCount up (ceil)", () => {
    render(<Pagination page={1} pageSize={10} total={11} onPage={() => {}} />);
    expect(screen.getByText(t("pagination.pageOf", { page: 1, pageCount: 2 }))).toBeInTheDocument();
  });

  it("renders in English", () => {
    setLocale("en", { persist: false });
    try {
      render(<Pagination page={2} pageSize={10} total={45} onPage={() => {}} />);
      expect(screen.getByRole("navigation", { name: "Pagination" })).toBeInTheDocument();
      expect(screen.getByText("11-20 of 45")).toBeInTheDocument();
      expect(screen.getByText("2 of 5")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Previous page" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Next page" })).toBeInTheDocument();
    } finally {
      setLocale("en", { persist: false });
    }
  });
});
