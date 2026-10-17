import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrandMark } from "./BrandMark";

describe("BrandMark", () => {
  it("renders the logo and the ICS wordmark by default", () => {
    render(<BrandMark />);
    expect(screen.getByText("ICS")).toBeInTheDocument();
    const img = document.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toBe("/favicon.svg");
  });

  it("withWord=false hides the wordmark", () => {
    render(<BrandMark withWord={false} />);
    expect(screen.queryByText("ICS")).toBeNull();
  });

  it("respects a custom size", () => {
    render(<BrandMark size={48} />);
    const img = document.querySelector("img");
    expect(img?.getAttribute("src")).toBe("/logo.svg");
    expect(img?.getAttribute("width")).toBe("48");
    expect(img?.getAttribute("height")).toBe("48");
  });

  it("the img is aria-hidden (decorative)", () => {
    render(<BrandMark />);
    const img = document.querySelector("img");
    expect(img).toHaveAttribute("aria-hidden", "true");
  });
});
