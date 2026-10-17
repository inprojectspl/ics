import { FileText, FolderKanban, GitBranch, KeyRound, Share2, ShieldCheck, type LucideIcon } from "lucide-react";
import { hasMessage, t, type MessageKey } from "../../lib/i18n";

/** What an audit event is about, for the icon and the filter groups. */
export type AuditCategory = "account" | "documents" | "sharing" | "projects" | "admin" | "integrations";

export const AUDIT_CATEGORIES: readonly AuditCategory[] = ["account", "documents", "sharing", "projects", "admin", "integrations"];

export const CATEGORY_ICON: Record<AuditCategory, LucideIcon> = {
  account: KeyRound,
  documents: FileText,
  sharing: Share2,
  projects: FolderKanban,
  admin: ShieldCheck,
  integrations: GitBranch,
};

export const CATEGORY_LABEL: Record<AuditCategory, MessageKey> = {
  account: "adminAudit.category.account",
  documents: "adminAudit.category.documents",
  sharing: "adminAudit.category.sharing",
  projects: "adminAudit.category.projects",
  admin: "adminAudit.category.admin",
  integrations: "adminAudit.category.integrations",
};

const ADMIN_USER_ACTIONS = /^user_(role|quota|bundle_limit|autobypass|display_name)_changed$|^user_.*_by_admin$|^user_reinvited$/;

/** Category from the action code; the vocabulary is `AuditAction` in `app/constants.py`. */
export function auditCategory(action: string): AuditCategory {
  if (action.startsWith("share_") || action.startsWith("asset_share_") || action.startsWith("asset_project_share_")) return "sharing";
  if (action.startsWith("project_") || action === "asset_project_changed") return "projects";
  if (action.startsWith("binding_")) return "integrations";
  if (
    ADMIN_USER_ACTIONS.test(action) ||
    action === "user_invited" ||
    action.startsWith("security_bypass_") ||
    action.startsWith("cdn_") ||
    action.startsWith("doc_type_")
  ) {
    return "admin";
  }
  if (
    action.startsWith("asset_") ||
    action.startsWith("vault_file_") ||
    action.startsWith("comment_") ||
    action.startsWith("relation_") ||
    action.startsWith("external_ref")
  ) {
    return "documents";
  }
  return "account";
}

/** Refusals and lockouts: the events an admin scans the log for. */
export function isAlarm(action: string): boolean {
  return /_(failed|rate_limited|locked)$/.test(action) || action === "user_locked_by_admin";
}

/** Readable name of the event; an action added on the backend before its label shows as the code. */
export function actionLabel(action: string): string {
  const key = `auditAction.${action}`;
  return hasMessage(key) ? t(key) : action;
}

/** Readable name of a payload field; a field without one shows its key. */
export function fieldLabel(key: string): string {
  const k = `auditField.${key}`;
  return hasMessage(k) ? t(k) : key;
}
