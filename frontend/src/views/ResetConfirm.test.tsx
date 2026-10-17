import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ApiError } from "../api/_core";
import { ResetConfirm } from "./ResetConfirm";

const passwordResetConfirm = vi.fn();

vi.mock("../api", () => ({
  api: { passwordResetConfirm: (...a: unknown[]) => passwordResetConfirm(...a) },
}));

function submit() {
  fireEvent.change(screen.getByLabelText("New password (at least 8 characters)"), {
    target: { value: "newpassword" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Change password" }));
}

beforeEach(() => {
  passwordResetConfirm.mockReset();
});

describe("ResetConfirm", () => {
  it("sets the new password and leads to login", async () => {
    passwordResetConfirm.mockResolvedValue({ ok: true });
    const onDone = vi.fn();
    render(<ResetConfirm token="tok" onDone={onDone} />);
    submit();
    fireEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(passwordResetConfirm).toHaveBeenCalledWith("tok", "newpassword");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("shows the server error and keeps the form", async () => {
    passwordResetConfirm.mockRejectedValue(new ApiError(400, "invalid token", "invalid token", "token_invalid"));
    render(<ResetConfirm token="tok" onDone={vi.fn()} />);
    submit();
    expect(await screen.findByText("The link is invalid.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change password" })).toBeInTheDocument();
  });
});
