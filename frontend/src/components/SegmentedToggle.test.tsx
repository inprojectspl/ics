import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SegmentedToggle } from "./SegmentedToggle";

const options = [
  { value: "a", label: "Option A" },
  { value: "b", label: "Option B" },
] as const;

describe("SegmentedToggle", () => {
  it("renders every option", () => {
    render(
      <SegmentedToggle
        value="a"
        onChange={() => {}}
        options={options as unknown as { value: string; label: string }[]}
        ariaLabel="Choose"
      />,
    );
    expect(screen.getByText("Option A")).toBeInTheDocument();
    expect(screen.getByText("Option B")).toBeInTheDocument();
  });

  it("aria-checked=true only on the active option", () => {
    render(
      <SegmentedToggle
        value="b"
        onChange={() => {}}
        options={options as unknown as { value: string; label: string }[]}
        ariaLabel="X"
      />,
    );
    const radios = screen.getAllByRole("radio");
    const checked = radios.filter((r) => r.getAttribute("aria-checked") === "true");
    expect(checked).toHaveLength(1);
    expect(checked[0]).toHaveTextContent("Option B");
  });

  it("clicking an option calls onChange with its value", () => {
    const onChange = vi.fn();
    render(
      <SegmentedToggle
        value="a"
        onChange={onChange}
        options={options as unknown as { value: string; label: string }[]}
        ariaLabel="X"
      />,
    );
    fireEvent.click(screen.getByText("Option B"));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("has role=radiogroup with an aria-label", () => {
    render(
      <SegmentedToggle
        value="a"
        onChange={() => {}}
        options={options as unknown as { value: string; label: string }[]}
        ariaLabel="Pick one"
      />,
    );
    expect(screen.getByRole("radiogroup")).toHaveAttribute(
      "aria-label",
      "Pick one",
    );
  });
});
