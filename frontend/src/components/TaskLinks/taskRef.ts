import type { ExternalRef, ExternalRefRole } from "../../api";
import type { MessageKey } from "../../lib/i18n";

export const ROLE_LABEL: Record<ExternalRefRole, MessageKey> = {
  context: "taskLinks.roleContext",
  deliverable: "taskLinks.roleDeliverable",
  reference: "taskLinks.roleReference",
};

/** Enough of a task reference to name it; external refs and project tasks both fit. */
type TaskRefParts = Pick<ExternalRef, "external_id" | "external_scope"> & { system: string; entity: string };

/** How the task is named in the list: `#4711` for a work package, `scope/node` for a PS node. */
export function refNumber(ref: TaskRefParts): string {
  if (ref.system === "openproject" && ref.entity === "work_package") return `#${ref.external_id}`;
  if (ref.external_scope) return `${ref.external_scope}/${ref.external_id}`;
  return ref.external_id;
}

/** Only http(s) addresses become links; anything else (`javascript:`, typos) stays text. */
export function safeUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}
