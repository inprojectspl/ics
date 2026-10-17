import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SecurityBadge } from "./SecurityBadge";

describe("SecurityBadge", () => {
  it("renders nothing when the status is clean (no-news indicator)", () => {
    const { container } = render(<SecurityBadge status="clean" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the status is null/undefined", () => {
    const { container: c1 } = render(<SecurityBadge status={null} />);
    const { container: c2 } = render(<SecurityBadge status={undefined} />);
    expect(c1.firstChild).toBeNull();
    expect(c2.firstChild).toBeNull();
  });

  it("renders 'Critical' for critical", () => {
    render(<SecurityBadge status="critical" />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("renders 'Warning' for warn", () => {
    render(<SecurityBadge status="warn" />);
    expect(screen.getByText("Warning")).toBeInTheDocument();
  });

  it("has a descriptive title for a11y and the tooltip", () => {
    const { container } = render(<SecurityBadge status="critical" />);
    // The title sits on the outer <span>; getByText would return the text node.
    const outer = container.querySelector("[title]");
    expect(outer).not.toBeNull();
    expect(outer?.getAttribute("title")).toMatch(/critical/i);
  });
});
