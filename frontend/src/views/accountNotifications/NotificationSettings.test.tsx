import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { Me } from "../../api";
import type { NotificationPreferences, WatchItem } from "../../api/notificationTypes";
import { ToastProvider } from "../../components/Toast";
import { renderWithClient } from "../../test-utils";
import { mkPrefs } from "../../test-notifications";
import { NotificationSettingsLazy } from "./lazy";
import { NotificationSettings } from "./NotificationSettings";

const api = vi.hoisted(() => ({
  getPreferences: vi.fn(),
  updatePreferences: vi.fn(),
  sendChatTest: vi.fn(),
  listPushDevices: vi.fn(),
  deletePushDevice: vi.fn(),
  listWatches: vi.fn(),
  clearAssetWatch: vi.fn(),
  clearProjectWatch: vi.fn(),
  WATCHES_PAGE_SIZE: 25,
}));
vi.mock("../../api/notifications", () => api);
const push = vi.hoisted(() => ({
  pushSupport: vi.fn(),
  isBrave: vi.fn(),
  enablePush: vi.fn(),
  disablePushHere: vi.fn(),
  hasPushHere: vi.fn(),
  thisDeviceId: vi.fn(),
}));
vi.mock("../../lib/notifications/push", () => push);
vi.mock("../../components/ViewerChrome", () => ({ ViewerChrome: () => null }));
const confirm = vi.fn();
vi.mock("../../components/ConfirmDialog", () => ({ useConfirm: () => confirm }));

const me = { id: "u1", email: "a@example.com", display_name: null, role: "user" } as Me;
let prefs: NotificationPreferences;
const watches: WatchItem[] = [
  { type: "project", level: "all", created_at: "2026-09-01T00:00:00Z", project: { slug: "crm", name: "CRM" } },
  {
    type: "asset",
    level: "watch",
    created_at: "2026-09-01T00:00:00Z",
    asset: { id: "a1", slug: "s1", title: "API spec", kind: "md_single" },
  },
  {
    type: "asset",
    level: "mute",
    created_at: "2026-09-01T00:00:00Z",
    asset: { id: "a2", slug: "s2", title: "", kind: "pdf_doc" },
  },
];

beforeEach(() => {
  prefs = mkPrefs();
  api.getPreferences.mockReset().mockImplementation(async () => prefs);
  api.updatePreferences.mockReset().mockImplementation(async (patch: Record<string, unknown>) => {
    if ("chat_webhook_url" in patch) {
      const configured = patch.chat_webhook_url !== null;
      return { ...prefs, chat: { configured, space: configured ? "spaces/AAAAbbbbCCCCdddd" : null, enabled: configured, error_code: null } };
    }
    const { events, ...rest } = patch as { events?: NotificationPreferences["events"] };
    return { ...prefs, ...rest, events: { ...prefs.events, ...events } };
  });
  api.sendChatTest.mockReset().mockResolvedValue(undefined);
  api.listPushDevices.mockReset().mockResolvedValue({
    items: [
      { id: "d1", label: "Chrome · macOS", created_at: "2026-09-01T00:00:00Z", last_success_at: "2026-09-20T00:00:00Z" },
      { id: "d2", label: "Firefox · Linux", created_at: "2026-09-02T00:00:00Z", last_success_at: null },
    ],
  });
  api.deletePushDevice.mockReset().mockResolvedValue(undefined);
  api.listWatches.mockReset().mockResolvedValue({ items: watches, total: 30 });
  api.clearAssetWatch.mockReset().mockResolvedValue({});
  api.clearProjectWatch.mockReset().mockResolvedValue({});
  push.pushSupport.mockReset().mockReturnValue("supported");
  push.isBrave.mockReset().mockReturnValue(false);
  push.enablePush.mockReset().mockResolvedValue("enabled");
  push.disablePushHere.mockReset().mockResolvedValue(undefined);
  push.hasPushHere.mockReset().mockResolvedValue(false);
  push.thisDeviceId.mockReset().mockReturnValue("d1");
  confirm.mockReset().mockResolvedValue(true);
});

function renderPage() {
  return renderWithClient(
    <ToastProvider>
      <NotificationSettings me={me} />
    </ToastProvider>,
  );
}

const section = (name: string) => screen.getByRole("region", { name });

describe("NotificationSettings", () => {
  it("loads lazily", async () => {
    renderWithClient(
      <ToastProvider>
        <Suspense fallback={null}>
          <NotificationSettingsLazy me={me} />
        </Suspense>
      </ToastProvider>,
    );
    expect(await screen.findByRole("switch", { name: "Notifications" })).toBeInTheDocument();
  });

  it("switches everything off optimistically", async () => {
    renderPage();
    const master = await screen.findByRole("switch", { name: "Notifications" });
    fireEvent.click(master);
    await waitFor(() => expect(master).toHaveAttribute("aria-checked", "false"));
    expect(api.updatePreferences).toHaveBeenCalledWith({ enabled: false });
  });

  it("sets the e-mail mode, or explains why it is off", async () => {
    const view = renderPage();
    fireEvent.click(await screen.findByRole("radio", { name: /^Daily/ }));
    await waitFor(() => expect(api.updatePreferences).toHaveBeenCalledWith({ email_mode: "daily" }));
    view.unmount();

    prefs = mkPrefs({ email_available: false });
    renderPage();
    expect(await screen.findByRole("radio", { name: /^Daily/ })).toBeDisabled();
    expect(screen.getByText(/The server has no e-mail configured, so/)).toBeInTheDocument();
  });

  it("enables push on this device only after the click and lists the devices", async () => {
    renderPage();
    const enable = await screen.findByRole("button", { name: "Enable on this device" });
    expect(push.enablePush).not.toHaveBeenCalled();
    await waitFor(() => expect(enable).toBeEnabled());
    fireEvent.click(enable);
    await waitFor(() => expect(push.enablePush).toHaveBeenCalledWith("BAAA"));

    const list = screen.getByRole("list", { name: "Devices with notifications" });
    expect(within(list).getByText("this device")).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: "Remove device Firefox · Linux" }));
    await waitFor(() => expect(api.deletePushDevice).toHaveBeenCalledWith("d2"));
    fireEvent.click(within(list).getByRole("button", { name: "Remove device Chrome · macOS" }));
    await waitFor(() => expect(push.disablePushHere).toHaveBeenCalled());
  });

  it("hides push when the server has no key and shows the browser hints", async () => {
    push.pushSupport.mockReturnValue("ios-install");
    push.isBrave.mockReturnValue(true);
    const view = renderPage();
    expect(await screen.findByText(/home screen/)).toBeInTheDocument();
    expect(screen.getByText(/Use Google services for push messaging/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Enable on this device" })).toBeNull();
    view.unmount();

    prefs = mkPrefs({ push: { available: false, public_key: null } });
    renderPage();
    await screen.findByRole("switch", { name: "Notifications" });
    expect(screen.queryByText(/You enable them on each device separately/)).toBeNull();
  });

  it("offers to turn push off where it is on", async () => {
    push.hasPushHere.mockResolvedValue(true);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Turn off on this device" }));
    await waitFor(() => expect(push.disablePushHere).toHaveBeenCalled());
  });

  it("validates, saves, tests and removes the Google Chat webhook", async () => {
    renderPage();
    const input = await screen.findByLabelText("Google Chat webhook URL");
    expect(screen.getByText(/will see document titles/)).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "https://evil.example/hook" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(api.updatePreferences).not.toHaveBeenCalled();

    const url = "https://chat.googleapis.com/v1/spaces/AAAA/messages?key=k&token=t";
    fireEvent.change(input, { target: { value: url } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.updatePreferences).toHaveBeenCalledWith({ chat_webhook_url: url }));
    expect(await screen.findByText("spaces/AAAA…dddd")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Send test" }));
    expect(await screen.findByText("Test message sent.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove webhook" }));
    await waitFor(() => expect(api.updatePreferences).toHaveBeenCalledWith({ chat_webhook_url: null }));
    expect(await screen.findByLabelText("Google Chat webhook URL")).toBeInTheDocument();
  });

  it("shows why the webhook stopped and lets the user switch it", async () => {
    prefs = mkPrefs({ chat: { configured: true, space: "spaces/X", enabled: false, error_code: "webhook_gone" } });
    renderPage();
    expect(await screen.findByText(/Error code: webhook_gone/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Send to this space" }));
    await waitFor(() => expect(api.updatePreferences).toHaveBeenCalledWith({ chat_enabled: true }));
    fireEvent.click(screen.getByRole("button", { name: "Change URL" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Google Chat webhook URL")).toBeNull();
  });

  it("switches an event channel in the matrix and in the phone chips", async () => {
    renderPage();
    const matrix = await screen.findByRole("region", { name: "What to notify about" });
    const cell = within(matrix).getByRole("checkbox", { name: "Document deleted: Browser" });
    fireEvent.click(cell);
    await waitFor(() =>
      expect(api.updatePreferences).toHaveBeenCalledWith({ events: { "asset.deleted": ["push"] } }),
    );
    // E-mail is off, so its column cannot be ticked.
    expect(within(matrix).getByRole("checkbox", { name: "Document deleted: E-mail" })).toBeDisabled();

    // In-app is always on: a fixed column, nothing to switch.
    expect(within(matrix).queryByRole("checkbox", { name: /In the app/ })).toBeNull();
    expect(within(matrix).queryByRole("button", { name: "In the app" })).toBeNull();

    const chips = within(matrix).getAllByRole("button", { name: "Browser" });
    fireEvent.click(chips[0] as HTMLElement);
    await waitFor(() =>
      expect(api.updatePreferences).toHaveBeenCalledWith({ events: { "asset.created": ["push"] } }),
    );
  });

  it("toggles notifications about own documents", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("switch", { name: "Changes to my documents" }));
    await waitFor(() => expect(api.updatePreferences).toHaveBeenCalledWith({ watch_own_assets: false }));
  });

  it("lists watched items with unwatch and pages", async () => {
    renderPage();
    const watched = await screen.findByRole("list", { name: "Watched" });
    expect(within(watched).getByRole("link", { name: "CRM" })).toHaveAttribute("href", "/projects/crm");
    // An untitled document is listed by its slug.
    expect(within(watched).getByRole("link", { name: "s2" })).toHaveAttribute("href", "/v/s2");
    expect(within(watched).getByText("Muted")).toBeInTheDocument();
    fireEvent.click(within(watched).getByRole("button", { name: "Unwatch CRM" }));
    await waitFor(() => expect(api.clearProjectWatch).toHaveBeenCalledWith("crm"));
    fireEvent.click(within(watched).getByRole("button", { name: "Unwatch API spec" }));
    await waitFor(() => expect(api.clearAssetWatch).toHaveBeenCalledWith("a1"));
    fireEvent.click(within(section("Watched")).getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(api.listWatches).toHaveBeenCalledWith(2));
  });

  it("reports a failed load", async () => {
    api.getPreferences.mockRejectedValue(new Error("down"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("down");
  });
});
