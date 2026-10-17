import { t } from "../lib/i18n";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import type { AssetWatch } from "../api/notificationTypes";
import { renderWithClient } from "../test-utils";
import { ToastProvider } from "./Toast";
import { AssetWatchToggle, ProjectWatchToggle, assetWatchActive, assetWatchTitle } from "./WatchToggle";

const api = vi.hoisted(() => ({
  getAssetWatch: vi.fn(),
  setAssetWatch: vi.fn(),
  clearAssetWatch: vi.fn(),
  getProjectWatch: vi.fn(),
  setProjectWatch: vi.fn(),
  clearProjectWatch: vi.fn(),
}));
vi.mock("../api/notifications", () => api);

const none: AssetWatch = { level: null, via_project: null, own: false };

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.getAssetWatch.mockResolvedValue(none);
  api.setAssetWatch.mockImplementation(async (_id: string, level: "watch" | "mute") => ({ ...none, level }));
  api.clearAssetWatch.mockResolvedValue(none);
  api.getProjectWatch.mockResolvedValue({ level: null });
  api.setProjectWatch.mockImplementation(async (_slug: string, level: string) => ({ level }));
  api.clearProjectWatch.mockResolvedValue({ level: null });
});

function renderAsset(watch: AssetWatch) {
  api.getAssetWatch.mockResolvedValue(watch);
  return renderWithClient(
    <ToastProvider>
      <AssetWatchToggle assetId="a1" projectName="Client portal" />
    </ToastProvider>,
  );
}


describe("AssetWatchToggle", () => {
  it.each([
    // state, pressed, request made by the click
    ["not watched", none, false, () => expect(api.setAssetWatch).toHaveBeenCalledWith("a1", "watch")],
    ["watched", { ...none, level: "watch" }, true, () => expect(api.clearAssetWatch).toHaveBeenCalledWith("a1")],
    [
      "watched and through the project",
      { ...none, level: "watch", via_project: "all" },
      true,
      () => expect(api.setAssetWatch).toHaveBeenCalledWith("a1", "mute"),
    ],
    [
      "through the project",
      { ...none, via_project: "all" },
      true,
      () => expect(api.setAssetWatch).toHaveBeenCalledWith("a1", "mute"),
    ],
    ["own", { ...none, own: true }, true, () => expect(api.setAssetWatch).toHaveBeenCalledWith("a1", "mute")],
    [
      "muted against the project",
      { ...none, level: "mute", via_project: "new" },
      false,
      () => expect(api.clearAssetWatch).toHaveBeenCalledWith("a1"),
    ],
  ] as const)("%s: pressed=%s, the click sends the right change", async (_name, watch, pressed, check) => {
    renderAsset(watch as AssetWatch);
    const button = await screen.findByRole("button", { pressed });
    fireEvent.click(button);
    await waitFor(check);
  });

  it("shows the state as a label and explains the click in the tooltip", async () => {
    renderAsset({ ...none, via_project: "all" });
    const button = await screen.findByRole("button", { pressed: true });
    const why = "You are watching this document through the project Client portal. Click to mute it";
    expect(button).toHaveAttribute("title", why);
    expect(button).toHaveTextContent(t("watch.watching"));
    // The explanation is part of the name, not only of the hover tooltip.
    expect(button).toHaveAccessibleName(`${t("watch.watching")}. ${why}`);
  });

  it("labels a muted document as muted", async () => {
    renderAsset({ ...none, level: "mute" });
    const button = await screen.findByRole("button", { pressed: false });
    expect(button).toHaveTextContent(t("watch.muted"));
  });

  it("flips at once and rolls back when the server refuses", async () => {
    let fail: (err: Error) => void = () => {};
    api.setAssetWatch.mockReturnValue(new Promise((_r, reject) => (fail = reject)));
    renderAsset(none);
    fireEvent.click(await screen.findByRole("button", { pressed: false }));
    expect(await screen.findByRole("button", { pressed: true })).toBeInTheDocument();
    fail(new Error("nope"));
    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
    expect(await screen.findByRole("button", { pressed: false })).toBeInTheDocument();
  });
});

describe("assetWatch helpers", () => {
  it("names every state", () => {
    expect(assetWatchActive({ ...none, level: "mute", own: true })).toBe(false);
    expect(assetWatchTitle({ ...none, level: "mute" }, null)).toMatch(/muted/);
    expect(assetWatchTitle({ ...none, level: "watch" }, null)).toBe("You are watching this document. Click to stop");
    expect(assetWatchTitle({ ...none, level: "watch", own: true }, null)).toMatch(/to mute it/);
    expect(assetWatchTitle({ ...none, via_project: "new" }, null)).toMatch(/through its project/);
    expect(assetWatchTitle({ ...none, own: true }, null)).toMatch(/your document/);
    expect(assetWatchTitle(none, null)).toBe("You are not watching this document. Click to watch it");
  });
});

describe("ProjectWatchToggle", () => {
  it("watches all activity and stops again", async () => {
    renderWithClient(
      <ToastProvider>
        <ProjectWatchToggle slug="crm" />
      </ToastProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { pressed: false }));
    await waitFor(() => expect(api.setProjectWatch).toHaveBeenCalledWith("crm", "all"));
    const on = await screen.findByRole("button", { pressed: true });
    expect(on).toHaveAccessibleName(/You are watching this project/);
    fireEvent.click(on);
    await waitFor(() => expect(api.clearProjectWatch).toHaveBeenCalledWith("crm"));
  });

  it("treats the new-documents level as watching", async () => {
    api.getProjectWatch.mockResolvedValue({ level: "new" });
    renderWithClient(
      <ToastProvider>
        <ProjectWatchToggle slug="crm" />
      </ToastProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { pressed: true }));
    await waitFor(() => expect(api.clearProjectWatch).toHaveBeenCalledWith("crm"));
  });
});
