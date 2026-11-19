import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

import { ApiError } from "../api/_core";
import { t } from "../lib/i18n";
import { renderWithClient } from "../test-utils";
import { AcceptInvite } from "./AcceptInvite";

const me = vi.fn();
const acceptProjectInvite = vi.fn();
const getProjectInvitation = vi.fn();
const acceptProjectInvitation = vi.fn();
const declineProjectInvitation = vi.fn();

vi.mock("../api", () => ({
  api: {
    me: (...a: unknown[]) => me(...a),
    acceptProjectInvite: (...a: unknown[]) => acceptProjectInvite(...a),
    getProjectInvitation: (...a: unknown[]) => getProjectInvitation(...a),
    acceptProjectInvitation: (...a: unknown[]) => acceptProjectInvitation(...a),
    declineProjectInvitation: (...a: unknown[]) => declineProjectInvitation(...a),
  },
}));

const invitation = {
  project_name: "Alpha",
  role: "viewer",
  invited_by: "ola",
  accepted: false,
};

beforeEach(() => {
  me.mockReset().mockResolvedValue({ id: "u1" });
  acceptProjectInvite.mockReset();
  getProjectInvitation.mockReset().mockResolvedValue(invitation);
  acceptProjectInvitation.mockReset();
  declineProjectInvitation.mockReset();
  window.history.replaceState({}, "", "/invite?token=tok");
});

describe("AcceptInvite", () => {
  it("shows a checking state while the invite is being accepted", async () => {
    acceptProjectInvite.mockReturnValue(new Promise(() => {}));
    renderWithClient(<AcceptInvite slug="alpha" token="tok" />);
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
    renderWithClient(<AcceptInvite slug="alpha" token="tok" />);
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
    renderWithClient(<AcceptInvite slug="alpha" token="tok" />);
    expect(await screen.findByText("alpha")).toBeInTheDocument();
  });

  it("sends an anonymous visitor to login with a return path", async () => {
    me.mockRejectedValue(new Error("401"));
    renderWithClient(<AcceptInvite slug="alpha" token="tok" />);
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
    renderWithClient(<AcceptInvite slug="alpha" token="tok" />);
    expect(
      await screen.findByText("Could not accept the invitation"),
    ).toBeInTheDocument();
  });

  it("reports a failed accept request", async () => {
    acceptProjectInvite.mockRejectedValue(
      new ApiError(410, "invitation expired", "invitation expired", "invitation_expired"),
    );
    renderWithClient(<AcceptInvite slug="alpha" token="tok" />);
    expect(await screen.findByText(t("error.invitation_expired"))).toBeInTheDocument();
    expect(screen.queryByText(/invitation expired/)).toBeNull();
    expect(screen.getByRole("link", { name: "Back to projects" })).toHaveAttribute(
      "href",
      "/projects",
    );
  });

  describe("from the inbox, without the e-mail token", () => {
    it("shows who invites with which role and accepts on request", async () => {
      acceptProjectInvitation.mockResolvedValue({
        accepted: true,
        project_slug: "alpha",
        project_name: "Alpha",
        role: "viewer",
      });
      renderWithClient(<AcceptInvite slug="alpha" token="" />);
      expect(
        await screen.findByText(t("acceptInvite.invitedBy", { name: "ola", project: "Alpha", role: "viewer" })),
      ).toBeInTheDocument();
      expect(acceptProjectInvite).not.toHaveBeenCalled();
      expect(acceptProjectInvitation).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: t("acceptInvite.accept") }));
      expect(await screen.findByRole("link", { name: "Open project" })).toHaveAttribute("href", "/projects/alpha");
      expect(acceptProjectInvitation).toHaveBeenCalledWith("alpha");
    });

    it("declines", async () => {
      declineProjectInvitation.mockResolvedValue({ declined: true });
      renderWithClient(<AcceptInvite slug="alpha" token="" />);
      fireEvent.click(await screen.findByRole("button", { name: t("acceptInvite.decline") }));
      expect(await screen.findByText(t("acceptInvite.declined"))).toBeInTheDocument();
      expect(declineProjectInvitation).toHaveBeenCalledWith("alpha");
    });

    it("goes straight to the project once the invitation is accepted", async () => {
      getProjectInvitation.mockResolvedValue({ ...invitation, accepted: true });
      renderWithClient(<AcceptInvite slug="alpha" token="" />);
      expect(await screen.findByRole("link", { name: "Open project" })).toHaveAttribute("href", "/projects/alpha");
    });

    it("says when the invitation is gone", async () => {
      getProjectInvitation.mockRejectedValue(
        new ApiError(404, "invitation not found", "invitation not found", "invitation_not_found"),
      );
      renderWithClient(<AcceptInvite slug="alpha" token="" />);
      expect(await screen.findByRole("link", { name: "Back to projects" })).toBeInTheDocument();
    });
  });
});
