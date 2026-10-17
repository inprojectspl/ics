import { describe, expect, it } from "vitest";
import { t } from "../../lib/i18n";
import { actionLabel, auditCategory, fieldLabel, isAlarm } from "./auditActions";

describe("auditCategory", () => {
  it.each([
    ["login_ok", "account"],
    ["pat_created", "account"],
    ["asset_uploaded", "documents"],
    ["vault_file_moved", "documents"],
    ["relation_added", "documents"],
    ["external_refs_rekeyed", "documents"],
    ["share_created", "sharing"],
    ["asset_share_granted", "sharing"],
    ["asset_project_share_added", "sharing"],
    ["project_member_kicked", "projects"],
    ["asset_project_changed", "projects"],
    ["binding_sync_failed", "integrations"],
    ["user_role_changed", "admin"],
    ["user_locked_by_admin", "admin"],
    ["user_reinvited", "admin"],
    ["user_invited", "admin"],
    ["security_bypass_granted", "admin"],
    ["cdn_allowlist_added", "admin"],
    ["doc_type_updated", "admin"],
  ])("%s belongs to %s", (action, category) => {
    expect(auditCategory(action)).toBe(category);
  });
});

describe("isAlarm", () => {
  it("flags refusals and lockouts only", () => {
    for (const a of ["login_failed", "login_rate_limited", "account_locked", "share_password_failed", "user_locked_by_admin"]) {
      expect(isAlarm(a)).toBe(true);
    }
    for (const a of ["login_ok", "user_unlocked_by_admin", "asset_deleted"]) expect(isAlarm(a)).toBe(false);
  });
});

describe("labels", () => {
  it("names known actions and fields, and falls back to the code", () => {
    expect(actionLabel("share_created")).toBe(t("auditAction.share_created"));
    expect(actionLabel("not_a_real_action")).toBe("not_a_real_action");
    expect(fieldLabel("asset_id")).toBe(t("auditField.asset_id"));
    expect(fieldLabel("mystery_field")).toBe("mystery_field");
  });
});
