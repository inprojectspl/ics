import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FileText } from "lucide-react";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders the title", () => {
    render(<EmptyState icon={FileText} title="No files" />);
    expect(screen.getByText("No files")).toBeInTheDocument();
  });

  it("renders the description when given", () => {
    render(
      <EmptyState
        icon={FileText}
        title="Empty"
        description="Drop a file here"
      />,
    );
    expect(screen.getByText("Drop a file here")).toBeInTheDocument();
  });

  it("renders no description section without a description", () => {
    render(<EmptyState icon={FileText} title="X" />);
    // Only the title paragraph is rendered.
    expect(screen.getAllByText(/./).length).toBe(1);
  });

  it("renders the action slot", () => {
    render(
      <EmptyState
        icon={FileText}
        title="X"
        action={<button>Add</button>}
      />,
    );
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });
});
