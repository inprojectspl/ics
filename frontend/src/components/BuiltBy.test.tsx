import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BuiltBy } from "./BuiltBy";
import { RailCredit } from "./shell/SidebarGroup";

describe("BuiltBy", () => {
  it("links to inProjects.ai in a new tab without leaking the opener", () => {
    render(<BuiltBy variant="page" />);
    const link = screen.getByRole("link", { name: "Built by inProjects.ai (opens in a new tab)" });
    expect(link).toHaveAttribute("href", "https://inprojects.ai");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveTextContent("Built by");
  });

  it("the rail variant shows the mark without the wordmark", () => {
    const { container } = render(<RailCredit />);
    expect(screen.getByRole("link", { name: /inProjects\.ai/ })).not.toHaveTextContent("Built by");
    expect(container.querySelectorAll("path[fill='currentColor']")).toHaveLength(0);
  });

  it("the full logo keeps distinct gradient ids per instance", () => {
    const { container } = render(
      <>
        <BuiltBy variant="page" />
        <BuiltBy variant="sidebar" />
      </>,
    );
    const ids = [...container.querySelectorAll("linearGradient")].map((g) => g.id);
    expect(new Set(ids).size).toBe(2);
  });
});
