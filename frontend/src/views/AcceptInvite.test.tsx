import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { ApiError } from "../api/_core";
import { t } from "../lib/i18n";
import { AcceptInvite } from "./AcceptInvite";

const me = vi.fn();
const acceptProjectInvite = vi.fn();

vi.mock("../api", () => ({
  api: {
    me: (...a: unknown[]) => me(...a),
    acceptProjectInvite: (...a: unknown[]) => acceptProjectInvite(...a),
  },
}));

beforeEach(() => {
  me.mockReset().mockResolvedValue({ id: "u1" });
  acceptProjectInvite.mockReset();
  window.history.replaceState({}, "", "/invite?token=tok");
});

describe("AcceptInvite", () => {
  it("shows a checking state while the invite is being accepted", async () => {
    acceptProjectInvite.mockReturnValue(new Promise(() => {}));
    render(<AcceptInvite token="tok" />);
    expect(screen.getByText("Checking the invitation…")).toBeInTheDocument();
    await waitFor(() => expect(acceptProjectInvite).toHaveBeenCalledWith("tok"));
    expect(screen.getByText("Checking the invitation…")).toBeInTheDocument();
  });

  it("accepts the invite and links to the project", async () => {
    acceptProjectInvite.mockResolvedValue({
      accepted: true,
      project_slug: "alpha",
      project_name: "Alpha",
      role: "editor",
    });
    render(<AcceptInvite token="tok" />);
    const link = await screen.findByRole("link", { name: "Open project" });
    expect(link).toHaveAttribute("href", "/projects/alpha");
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("editor")).toBeInTheDocument();
  });

  it("falls back to the slug when the project has no name", async () => {
    acceptProjectInvite.mockResolvedValue({
      accepted: true,
      project_slug: "alpha",
      project_name: null,
      role: "viewer",
    });
    render(<AcceptInvite token="tok" />);
    expect(await screen.findByText("alpha")).toBeInTheDocument();
  });

  it("sends an anonymous visitor to login with a return path", async () => {
    me.mockRejectedValue(new Error("401"));
    render(<AcceptInvite token="tok" />);
    const link = await screen.findByRole("link", { name: "Sign in" });
    expect(link).toHaveAttribute(
      "href",
      `/#login?next=${encodeURIComponent("/invite?token=tok")}`,
    );
    expect(acceptProjectInvite).not.toHaveBeenCalled();
  });

  it("reports an invite the backend did not accept", async () => {
    acceptProjectInvite.mockResolvedValue({
      accepted: false,
      project_slug: null,
      project_name: null,
      role: "viewer",
    });
    render(<AcceptInvite token="tok" />);
    expect(
      await screen.findByText("Could not accept the invitation"),
    ).toBeInTheDocument();
  });

  it("reports a failed accept request", async () => {
    acceptProjectInvite.mockRejectedValue(
      new ApiError(410, "invitation expired", "invitation expired", "invitation_expired"),
    );
    render(<AcceptInvite token="tok" />);
    expect(await screen.findByText(t("error.invitation_expired"))).toBeInTheDocument();
    expect(screen.queryByText(/invitation expired/)).toBeNull();
    expect(screen.getByRole("link", { name: "Back to projects" })).toHaveAttribute(
      "href",
      "/projects",
    );
  });
});
