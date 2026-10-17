import { describe, expect, it } from "vitest";
import {
  describeWebhookUrlError,
  validateWebhookUrl,
} from "./notificationProviders";

describe("validateWebhookUrl(google_chat)", () => {
  it.each([
    "https://chat.googleapis.com/v1/spaces/AAA/messages?key=x&token=y",
    "https://chat.googleapis.com/v1/spaces/B/messages",
    "https://CHAT.GOOGLEAPIS.COM/x",
  ])("accepts the canonical URL %s", (url) => {
    expect(validateWebhookUrl("google_chat", url)).toBeNull();
  });

  it("expects a URL", () => {
    expect(validateWebhookUrl("google_chat", "")).toBe("empty");
    expect(validateWebhookUrl("google_chat", "   ")).toBe("empty");
  });

  it("rejects garbage", () => {
    expect(validateWebhookUrl("google_chat", "not a url")).toBe("malformed");
  });

  it("requires https (rejects http)", () => {
    expect(validateWebhookUrl("google_chat", "http://chat.googleapis.com/x")).toBe(
      "wrong_scheme",
    );
  });

  it("rejects user:pass@host", () => {
    expect(
      validateWebhookUrl("google_chat", "https://u:p@chat.googleapis.com/x"),
    ).toBe("has_userinfo");
  });

  it.each([
    "https://hooks.slack.com/services/T00/B00/abc",
    "https://chat.googleapis.com.attacker.example/x",
    "https://attacker.example/chat.googleapis.com",
    "https://127.0.0.1/x",
  ])("rejects a foreign host: %s", (url) => {
    expect(validateWebhookUrl("google_chat", url)).toBe("wrong_host");
  });
});

describe("describeWebhookUrlError", () => {
  it("returns a message for every error code", () => {
    expect(describeWebhookUrlError("empty")).toMatch(/URL/);
    expect(describeWebhookUrlError("malformed")).toMatch(/URL/);
    expect(describeWebhookUrlError("wrong_scheme")).toMatch(/https/);
    expect(describeWebhookUrlError("wrong_host")).toMatch(/chat.googleapis.com/);
    expect(describeWebhookUrlError("has_userinfo")).toMatch(/user/);
  });
});
