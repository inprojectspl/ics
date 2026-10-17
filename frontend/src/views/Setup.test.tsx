import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ApiError } from "../api/_core";
import { Setup } from "./Setup";

const setupFromToken = vi.fn();

vi.mock("../api", () => ({
  api: { setupFromToken: (...a: unknown[]) => setupFromToken(...a) },
}));

function submit(password: string, displayName?: string) {
  if (displayName !== undefined) {
    fireEvent.change(screen.getByLabelText("Display name (optional)"), {
      target: { value: displayName },
    });
  }
  fireEvent.change(screen.getByLabelText("Password (at least 8 characters)"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: "Set a password" }));
}

beforeEach(() => {
  setupFromToken.mockReset();
});

describe("Setup", () => {
  it("activates the account with the display name and leads to login", async () => {
    setupFromToken.mockResolvedValue({ ok: true });
    const onDone = vi.fn();
    render(<Setup token="tok" onDone={onDone} />);
    submit("longpassword", "Alice");
    fireEvent.click(await screen.findByRole("button", { name: "Go to sign in" }));
    expect(setupFromToken).toHaveBeenCalledWith("tok", "longpassword", "Alice");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("activates the account without a display name", async () => {
    setupFromToken.mockResolvedValue({ ok: true });
    render(<Setup token="tok" onDone={vi.fn()} />);
    const form = screen.getByRole("button", { name: "Set a password" }).closest("form");
    submit("longpassword");
    expect(form?.checkValidity()).toBe(true);
    await screen.findByRole("button", { name: "Go to sign in" });
    expect(setupFromToken).toHaveBeenCalledWith("tok", "longpassword", undefined);
  });

  it("shows the server error and keeps the form", async () => {
    setupFromToken.mockRejectedValue(new ApiError(400, "token expired", "token expired", "token_expired"));
    render(<Setup token="tok" onDone={vi.fn()} />);
    submit("longpassword", "Alice");
    expect(await screen.findByText("The link has expired. Ask for a new one.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set a password" })).not.toBeDisabled();
  });
});
