/** `GET /api/admin/audit` shapes (`app/routes/admin.py`). */

/** Name and in-app path of an id the log refers to. */
export type AuditRef = { label: string; href: string | null };

export type AuditEntry = {
  id: number;
  timestamp: string;
  actor: string;
  /** Readable name and in-app path of `actor`/`target`, when the row still exists
   * (no path for a deleted one). */
  actor_label: string | null;
  actor_href: string | null;
  action: string;
  target: string | null;
  target_label: string | null;
  target_href: string | null;
  payload: unknown;
  /** Names and paths of the ids in `payload`, per field. */
  payload_refs: Record<string, AuditRef[]>;
  ip_hash: string | null;
};

export type AuditPage = {
  items: AuditEntry[];
  next_cursor: number | null;
};
