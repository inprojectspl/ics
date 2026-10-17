import { memo, type ReactNode } from "react";
import { clsx } from "clsx";
import type { AuditEntry, AuditRef } from "../../api";
import { formatTime, formatTimestamp } from "../../lib/format";
import { t } from "../../lib/i18n";
import { AppLink } from "../../components/ui/AppLink";
import { DetailItem, DetailList } from "../../components/ui/DetailList";
import { ExpandableRow } from "../../components/ui/ExpandableRow";
import { CATEGORY_ICON, actionLabel, auditCategory, fieldLabel, isAlarm } from "./auditActions";

/** `user:alice@example.com` reads as the address; ids stay as they are. */
function readableRef(ref: string, label: string | null): string {
  if (label) return label;
  const value = ref.startsWith("user:") ? ref.slice("user:".length) : "";
  return value.includes("@") ? value : ref;
}

function formatValue(v: unknown): ReactNode {
  if (v === null || v === undefined || v === "") return <span className="text-text-tertiary">{t("adminAudit.none")}</span>;
  if (typeof v === "boolean") return v ? t("common.yes") : t("common.no");
  if (typeof v === "string" || typeof v === "number") return String(v);
  if (Array.isArray(v) && v.every((x) => typeof x !== "object")) return v.length ? v.join(", ") : t("adminAudit.none");
  return <pre className="whitespace-pre-wrap break-all font-code text-meta">{JSON.stringify(v, null, 2)}</pre>;
}

const LINK = "font-medium text-accent hover:underline";

function RefList({ refs }: { refs: AuditRef[] }) {
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1">
      {refs.map((ref, i) =>
        ref.href ? (
          <AppLink key={i} href={ref.href} className={LINK}>
            {ref.label}
          </AppLink>
        ) : (
          <span key={i}>{ref.label}</span>
        ),
      )}
    </span>
  );
}

/** A reference by name, linked when the row still exists; a deleted one says so. */
function RefValue({ raw, label, href }: { raw: string; label: string | null; href: string | null }) {
  return (
    <>
      <RefList refs={[{ label: readableRef(raw, label), href }]} />
      {label && !href && <span className="ml-2 text-meta text-text-secondary">{t("adminAudit.deleted")}</span>}
    </>
  );
}

/**
 * One event of the audit log: what happened, who did it and to what, in
 * words. Opened, it lists every stored field, the event's own details
 * (the payload) as a table rather than raw JSON.
 */
export const AuditRow = memo(function AuditRow({
  entry: r,
  open,
  onToggle,
}: {
  entry: AuditEntry;
  open: boolean;
  onToggle: (id: number) => void;
}) {
  const Icon = CATEGORY_ICON[auditCategory(r.action)];
  const alarm = isAlarm(r.action);
  const payload =
    r.payload && typeof r.payload === "object" && !Array.isArray(r.payload) ? Object.entries(r.payload) : [];
  const actor = readableRef(r.actor, r.actor_label);
  const targetText = r.target ? readableRef(r.target, r.target_label) : null;
  // A sign-in or a password change is about the actor; say the name once.
  const target = targetText === actor ? null : targetText;

  return (
    <ExpandableRow
      as="div"
      align="start"
      dense
      className="border-b border-border"
      open={open}
      onToggle={() => onToggle(r.id)}
      leading={
        <>
          <time dateTime={r.timestamp} className="shrink-0 pt-0.5 text-meta tabular-nums text-text-secondary sm:w-16">
            {formatTime(r.timestamp)}
          </time>
          <Icon size={16} aria-hidden className={clsx("mt-0.5 shrink-0", alarm ? "text-danger" : "text-text-secondary")} />
        </>
      }
      header={
        <>
          <span className={clsx("block text-ui font-medium", alarm ? "text-danger" : "text-text-primary")}>
            {actionLabel(r.action)}
          </span>
          <span className="block truncate text-meta text-text-secondary">
            {actor}
            {target && (
              <>
                <span aria-hidden> → </span>
                <span className="sr-only">{t("adminAudit.onTarget")} </span>
                {target}
              </>
            )}
          </span>
        </>
      }
    >
      <DetailList>
        <DetailItem label={t("adminAudit.who")}>
          <RefValue raw={r.actor} label={r.actor_label} href={r.actor_href} />
        </DetailItem>
        {r.target && (
          <DetailItem label={t("adminAudit.what")}>
            <RefValue raw={r.target} label={r.target_label} href={r.target_href} />
          </DetailItem>
        )}
        <DetailItem label={t("adminAudit.when")}>{formatTimestamp(r.timestamp)}</DetailItem>
        {payload.map(([k, v]) => (
          <DetailItem key={k} label={fieldLabel(k)}>
            {r.payload_refs?.[k] ? <RefList refs={r.payload_refs[k]} /> : formatValue(v)}
          </DetailItem>
        ))}
      </DetailList>
      <p className="mt-3 border-t border-border pt-3 text-meta font-medium text-text-secondary">{t("adminAudit.ids")}</p>
      <DetailList code className="mt-1 gap-y-1">
        <DetailItem label={t("adminAudit.event")}>{r.action}</DetailItem>
        <DetailItem label={t("adminAudit.who")}>{r.actor}</DetailItem>
        {r.target && <DetailItem label={t("adminAudit.what")}>{r.target}</DetailItem>}
        {r.ip_hash && <DetailItem label={t("adminAudit.ip")}>{r.ip_hash}</DetailItem>}
        <DetailItem label={t("adminAudit.entry")}>{String(r.id)}</DetailItem>
      </DetailList>
    </ExpandableRow>
  );
});
