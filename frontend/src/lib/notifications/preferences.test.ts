import { describe, expect, it } from "vitest";
import { mkPrefs } from "../../test-notifications";
import { applyPatch, channelBlocker, maskSpace, toggleChannel } from "./preferences";

describe("applyPatch", () => {
  it("merges switches, e-mail mode, events and the chat toggle", () => {
    const prefs = mkPrefs({ chat: { configured: true, space: "spaces/A", enabled: true, error_code: null } });
    const next = applyPatch(prefs, {
      enabled: false,
      email_mode: "daily",
      events: { "asset.deleted": ["email"] },
      chat_enabled: false,
    });
    expect(next.enabled).toBe(false);
    expect(next.email_mode).toBe("daily");
    expect(next.events["asset.deleted"]).toEqual(["email"]);
    expect(next.events["asset.created"]).toEqual([]);
    expect(next.chat.enabled).toBe(false);
    expect(applyPatch(prefs, {}).chat).toBe(prefs.chat);
  });
});

describe("toggleChannel", () => {
  it("adds and removes in the canonical channel order", () => {
    expect(toggleChannel(["chat"], "push")).toEqual(["push", "chat"]);
    expect(toggleChannel(["push", "chat"], "chat")).toEqual(["push"]);
  });
});

describe("channelBlocker", () => {
  it("names why a channel cannot deliver", () => {
    const prefs = mkPrefs();
    expect(channelBlocker(prefs, "push")).toBeNull();
    expect(channelBlocker(mkPrefs({ push: { available: false, public_key: null } }), "push")).toBe(
      "accountNotifications.blocked.push",
    );
    expect(channelBlocker(prefs, "email")).toBe("accountNotifications.blocked.emailOff");
    expect(channelBlocker(mkPrefs({ email_available: false }), "email")).toBe(
      "accountNotifications.blocked.emailServer",
    );
    expect(channelBlocker(mkPrefs({ email_mode: "batched" }), "email")).toBeNull();
    expect(channelBlocker(prefs, "chat")).toBe("accountNotifications.blocked.chatMissing");
    const chat = { configured: true, space: "s", enabled: false, error_code: null };
    expect(channelBlocker(mkPrefs({ chat }), "chat")).toBe("accountNotifications.blocked.chatOff");
    expect(channelBlocker(mkPrefs({ chat: { ...chat, enabled: true } }), "chat")).toBeNull();
  });
});

describe("maskSpace", () => {
  it("elides the middle of a long space id", () => {
    expect(maskSpace("spaces/AAAAbbbbCCCCdddd")).toBe("spaces/AAAA…dddd");
    expect(maskSpace("spaces/AB")).toBe("spaces/AB");
  });
});
