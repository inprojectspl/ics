import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { t, tn } from "../../lib/i18n";
import { mockMedia } from "../../test-media";

const state = vi.hoisted(() => ({ count: undefined as number | undefined, bumps: 0 }));
vi.mock("../../lib/notifications/queries", () => ({ useUnreadCount: () => state.count }));
vi.mock("../notifications/MenuNotifications", () => ({
  MenuNotifications: ({ unread }: { unread: number }) => <p>skrzynka {unread}</p>,
}));
vi.mock("../../lib/motion", async (orig) => ({
  ...(await orig<typeof import("../../lib/motion")>()),
  playEnter: (_el: unknown, preset: string) => {
    if (preset === "bump") state.bumps += 1;
  },
}));

import { NotificationsButton } from "./NotificationsButton";

describe("NotificationsButton", () => {
  it("names the unread count, shows it on the bell and bumps only on a rise", () => {
    mockMedia({ width: 1440 });
    state.count = undefined;
    const { rerender } = render(<NotificationsButton />);
    expect(screen.getByRole("button", { name: t("notifications.title") })).toBeInTheDocument();
    state.count = 3;
    rerender(<NotificationsButton />);
    const bell = screen.getByRole("button", { name: tn("notifications.openUnread", 3) });
    expect(bell).toHaveTextContent("3");
    expect(state.bumps).toBe(0);
    state.count = 5;
    rerender(<NotificationsButton />);
    expect(state.bumps).toBe(1);
    state.count = 2;
    rerender(<NotificationsButton />);
    expect(state.bumps).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: tn("notifications.openUnread", 2) }));
    expect(screen.getByText("skrzynka 2")).toBeInTheDocument();
  });

  it("caps a large count", () => {
    state.count = 250;
    render(<NotificationsButton />);
    expect(screen.getByRole("button")).toHaveTextContent("99+");
  });
});
