import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ApiError } from "../../api/_core";
import { NotificationsUnsubscribeLazy } from "./lazy";
import { NotificationsUnsubscribe } from "./Unsubscribe";

const unsubscribeEmail = vi.fn();
vi.mock("../../api/notifications", () => ({
  unsubscribeEmail: (...a: unknown[]) => unsubscribeEmail(...a),
}));

beforeEach(() => {
  unsubscribeEmail.mockReset().mockResolvedValue(undefined);
});

describe("NotificationsUnsubscribe", () => {
  it("sends the token only after the click", async () => {
    render(
      <Suspense fallback={null}>
        <NotificationsUnsubscribeLazy token="tok" />
      </Suspense>,
    );
    const button = await screen.findByRole("button", { name: "Unsubscribe" });
    expect(unsubscribeEmail).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(await screen.findByText("Unsubscribed")).toBeInTheDocument();
    expect(unsubscribeEmail).toHaveBeenCalledWith("tok");
  });

  it("explains a bad token", async () => {
    unsubscribeEmail.mockRejectedValue(new ApiError(400, "bad", "bad", "invalid_unsubscribe_token"));
    render(<NotificationsUnsubscribe token="tok" />);
    fireEvent.click(screen.getByRole("button", { name: "Unsubscribe" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The unsubscribe link is invalid or has expired.");
  });

  it("offers nothing to click without a token", () => {
    render(<NotificationsUnsubscribe token="" />);
    expect(screen.getByText(/The link is incomplete/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
