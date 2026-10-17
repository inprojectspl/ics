import { afterEach, describe, expect, it } from "vitest";
import en from "../locales/en.json";
import pl from "../locales/pl.json";
import { messageForCode, messageForStatus } from "./errorMessages";
import { setLocale } from "./i18n";

const catalogues: [locale: "pl" | "en", entries: Record<string, unknown>][] = [
  ["pl", pl],
  ["en", en],
];

afterEach(() => {
  setLocale("pl", { persist: false });
});

// Statuses of `_STATUS_CODES` in backend/app/errors.py, plus a 5xx.
const STATUSES = [400, 401, 403, 404, 405, 409, 410, 413, 415, 422, 429, 500];

// Document metadata (ADR-0015) and relation graph (ADR-0016) codes the forms show.
const DOMAIN_CODES = [
  "doc_type_unknown",
  "doc_type_filter_unknown",
  "metadata_invalid",
  "doc_type_schema_invalid",
  "relation_self",
  "relation_exists",
  "relation_type_invalid",
  "relation_limit",
  "relation_cycle",
  "relation_not_found",
  "relation_anchor_invalid",
  // Notifications (ADR-0023, docs/notifications-api.md).
  "invalid_cursor",
  "notification_not_found",
  "stream_browser_only",
  "invalid_webhook_url",
  "chat_not_configured",
  "chat_delivery_failed",
  "push_not_configured",
  "push_endpoint_not_allowed",
  "push_subscription_not_found",
  "invalid_unsubscribe_token",
];

describe("mapped error codes", () => {
  it.each(catalogues)("every status has generic copy in %s", (locale) => {
    setLocale(locale, { persist: false });
    for (const status of STATUSES) {
      expect(typeof messageForStatus(status), String(status)).toBe("string");
    }
  });

  it.each(catalogues)("every domain code has copy in %s", (locale, entries) => {
    setLocale(locale, { persist: false });
    for (const code of DOMAIN_CODES) {
      const copy = entries[`error.${code}`];
      expect(typeof copy, code).toBe("string");
      expect(messageForCode(code), code).toBe(copy);
    }
  });
});

describe("messageForCode", () => {
  it("returns undefined for a missing or unknown code", () => {
    expect(messageForCode(null)).toBeUndefined();
    expect(messageForCode("no_such_code")).toBeUndefined();
  });
});

describe("messageForStatus", () => {
  it("maps known statuses and every 5xx to their generic copy", () => {
    expect(messageForStatus(404)).toBe(messageForCode("not_found"));
    expect(messageForStatus(503)).toBe(messageForCode("server_error"));
    expect(messageForStatus(418)).toBeUndefined();
  });
});
