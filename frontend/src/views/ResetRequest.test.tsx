import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { ResetRequest } from "./ResetRequest";

const passwordResetRequest = vi.fn();

vi.mock("../api", () => ({
  api: { passwordResetRequest: (...a: unknown[]) => passwordResetRequest(...a) },
}));

function submit() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Send link" }));
}

beforeEach(() => {
  passwordResetRequest.mockReset();
});

describe("ResetRequest", () => {
  it("requests a reset link for the typed email", async () => {
    passwordResetRequest.mockResolvedValue({ ok: true });
    render(<ResetRequest />);
    submit();
    expect(await screen.findByText("Check your inbox")).toBeInTheDocument();
    expect(passwordResetRequest).toHaveBeenCalledWith("a@example.com");
  });

  it("shows the same confirmation when the request fails, so accounts cannot be probed", async () => {
    passwordResetRequest.mockRejectedValue(new Error("404"));
    render(<ResetRequest />);
    submit();
    expect(await screen.findByText("Check your inbox")).toBeInTheDocument();
  });
});
