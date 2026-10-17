import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { t } from "../lib/i18n";
import { SearchInput } from "./SearchInput";

describe("SearchInput", () => {
  it("renders an input with an aria-label", () => {
    render(<SearchInput value="" onChange={() => {}} ariaLabel="Search docs" />);
    expect(screen.getByLabelText("Search docs")).toBeInTheDocument();
  });

  it("the input value equals the value prop", () => {
    render(<SearchInput value="foo" onChange={() => {}} />);
    expect(screen.getByRole("searchbox")).toHaveValue("foo");
  });

  it("calls onChange with the new value while typing", () => {
    const onChange = vi.fn();
    render(<SearchInput value="" onChange={onChange} />);
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "alpha" },
    });
    expect(onChange).toHaveBeenCalledWith("alpha");
  });

  it("placeholder defaults to 'Search…'", () => {
    render(<SearchInput value="" onChange={() => {}} />);
    expect(screen.getByPlaceholderText("Search…")).toBeInTheDocument();
  });

  it("custom placeholder rendered", () => {
    render(<SearchInput value="" onChange={() => {}} placeholder="Find" />);
    expect(screen.getByPlaceholderText("Find")).toBeInTheDocument();
  });

  it("busy=true shows the search indicator", () => {
    render(<SearchInput value="abc" onChange={() => {}} busy />);
    expect(screen.getByLabelText(t("palette.searching"))).toBeInTheDocument();
    // While busy the clear button gives way to the indicator.
    expect(screen.queryByRole("button", { name: t("searchInput.clear") })).toBeNull();
  });

  it("an empty field has no clear button", () => {
    render(<SearchInput value="" onChange={() => {}} />);
    expect(screen.queryByRole("button", { name: t("searchInput.clear") })).toBeNull();
    expect(screen.queryByLabelText(t("palette.searching"))).toBeNull();
  });

  it("the clear button empties the field", () => {
    const onChange = vi.fn();
    render(<SearchInput value="abc" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: t("searchInput.clear") }));
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("Escape clears the typed value and does not propagate", () => {
    const onChange = vi.fn();
    const outer = vi.fn();
    document.addEventListener("keydown", outer);
    render(<SearchInput value="abc" onChange={onChange} />);
    fireEvent.keyDown(screen.getByRole("searchbox"), { key: "Escape" });
    expect(onChange).toHaveBeenCalledWith("");
    expect(outer).not.toHaveBeenCalled();
    document.removeEventListener("keydown", outer);
  });

  it("Escape in an empty field changes nothing", () => {
    const onChange = vi.fn();
    render(<SearchInput value="" onChange={onChange} />);
    fireEvent.keyDown(screen.getByRole("searchbox"), { key: "Escape" });
    expect(onChange).not.toHaveBeenCalled();
  });
});
