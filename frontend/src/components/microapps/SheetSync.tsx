import { memo, useCallback, useState } from "react";

import { ApiError } from "../../api/_core";
import {
  applySheetSync,
  checkSheetSync,
  previewSheetSync,
  requestSheetAccess,
  type SheetIssue,
  type SheetLink,
  type SheetOperation,
  type SheetPlace,
  type SheetStatus,
  type SheetUpdate,
} from "../../api/sheets";
import { extraList, extraString, formatApiError } from "../../lib/apiError";
import { formatRelative } from "../../lib/format";
import { t, tn, type MessageKey } from "../../lib/i18n";
import { Badge, type BadgeTone } from "../ui/Badge";
import { Button, buttonClass } from "../ui/Button";
import { DetailItem, DetailList } from "../ui/DetailList";

type Side = "app" | "sheet";
type Busy = "preview" | "apply" | "check" | "request" | null;

/** A preview that cannot be applied any more: only a new one helps. */
const PREVIEW_AGAIN = new Set(["sheet_changed", "app_changed", "sheet_link_changed"]);
/** Refusals over the app owner's row limit; `extra.limit` is that limit. */
const ROW_LIMIT_CODES = new Set(["sheet_too_large", "collection_too_large"]);

const STATE_LABEL: Record<SheetOperation["state"], MessageKey> = {
  previewed: "microapps.sheets.state.previewed",
  applying: "microapps.sheets.state.applying",
  applied: "microapps.sheets.state.applied",
  stale: "microapps.sheets.state.stale",
  superseded: "microapps.sheets.state.superseded",
  failed: "microapps.sheets.state.failed",
};

const GOOGLE_LABEL: Record<SheetOperation["google_status"], MessageKey> = {
  none: "microapps.sheets.google.status.none",
  pending: "microapps.sheets.google.status.pending",
  confirmed: "microapps.sheets.google.status.confirmed",
  uncertain: "microapps.sheets.google.status.uncertain",
  failed: "microapps.sheets.google.status.failed",
};

const GOOGLE_TONE: Record<SheetOperation["google_status"], BadgeTone> = {
  none: "neutral",
  pending: "neutral",
  confirmed: "success",
  uncertain: "warning",
  failed: "danger",
};

const conflictKey = (recordId: string, field: string) => `${recordId}:${field}`;

/** My last operation that still needs me: a preview to apply, an apply to
 * finish, or a write whose outcome Google did not confirm. */
function resumable(ops: SheetOperation[]): SheetOperation | null {
  const last = ops[0];
  if (!last?.mine) return null;
  const open = last.state === "previewed" || last.state === "applying" || last.unsettled;
  return open ? last : null;
}


/** How a change names its place: the collection when the link has several,
 * the tab when there is more than one, and the row in that tab. */
interface Places {
  collections: boolean;
  tabs: boolean;
}

function placesOf(link: SheetLink): Places {
  return {
    collections: link.mappings.length > 1,
    tabs: link.mappings.reduce((n, m) => n + m.tabs.length, 0) > 1,
  };
}

function placeLabel(item: SheetPlace, places: Places): string {
  const where =
    item.row === undefined
      ? (places.tabs && item.tab) || ""
      : places.tabs && item.tab
        ? t("microapps.sheets.rowIn", { tab: item.tab, row: item.row })
        : t("microapps.sheets.row", { row: item.row });
  return [places.collections ? item.collection : "", where].filter(Boolean).join(" · ");
}

type HeaderOf = (collection: string, field: string) => string;

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return t("microapps.sheets.value.empty");
  if (typeof value === "boolean") return t(value ? "common.yes" : "common.no");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * The sync, always started by a person: preview what would change, decide
 * each conflict, apply. A write Google did not confirm is never repeated by
 * itself; the person checks it.
 */
export function SheetSync({
  assetId,
  status,
  link,
  connectHref,
  onChanged,
}: {
  assetId: string;
  status: SheetStatus;
  link: SheetLink;
  connectHref: string;
  onChanged: () => Promise<void>;
}) {
  const [current, setCurrent] = useState<SheetOperation | null>(null);
  // Choices made here, over those an earlier apply of the same preview recorded.
  const [decisions, setDecisions] = useState<Record<string, Side>>({});
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);

  const decide = useCallback((key: string, side: Side) => setDecisions((d) => ({ ...d, [key]: side })), []);
  const op = current ?? resumable(status.operations);
  const chosen: Record<string, Side> = { ...op?.decisions, ...decisions };

  const run = async (kind: Exclude<Busy, null>, action: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (err) {
      setError(err);
      if (err instanceof ApiError && err.code && PREVIEW_AGAIN.has(err.code)) setCurrent(null);
    } finally {
      setBusy(null);
      await onChanged();
    }
  };

  const preview = () =>
    run("preview", async () => {
      const next = await previewSheetSync(assetId);
      setDecisions({});
      setCurrent(next);
    });
  const apply = (target: SheetOperation) =>
    run("apply", async () => setCurrent(await applySheetSync(assetId, target.id, chosen)));
  const check = (target: SheetOperation) =>
    run("check", async () => setCurrent(await checkSheetSync(assetId, target.id)));
  const requestAccess = () =>
    run("request", async () => {
      const r = await requestSheetAccess(assetId);
      setNotice(t(r.sent ? "microapps.sheets.access.sent" : "microapps.sheets.access.alreadyRequested"));
    });

  const ownerDisconnected = link.account_mode === "owner_account" && status.owner_google_connected === false;
  const needsMyGoogle = link.account_mode === "per_user" && !status.my_google;

  return (
    <div className="space-y-4">
      <p className="text-meta text-text-secondary">{t("microapps.sheets.sync.hint")}</p>
      {link.paused && <p className="text-ui text-warning">{t("microapps.sheets.sync.paused")}</p>}
      {ownerDisconnected && <p className="text-ui text-warning">{t("microapps.sheets.sync.ownerDisconnected")}</p>}
      {needsMyGoogle && <p className="text-ui text-warning">{t("microapps.sheets.sync.needsGoogle")}</p>}
      <Button variant={op?.state === "previewed" ? "secondary" : "primary"} busy={busy === "preview"} disabled={link.paused || blocked(busy, "preview")} onClick={() => void preview()}>
        {t("microapps.sheets.sync.preview")}
      </Button>

      <div aria-live="polite" className="space-y-4">
        {error !== null && (
          <SyncError
            error={error}
            link={link}
            isOwner={status.rights.owner}
            connectHref={connectHref}
            requesting={busy === "request"}
            onRequestAccess={() => void requestAccess()}
          />
        )}
        {notice && (
          <p role="status" className="text-ui text-success">
            {notice}
          </p>
        )}
        {op && (
          <OperationView
            op={op}
            places={placesOf(link)}
            chosen={chosen}
            busy={busy}
            onDecide={decide}
            onApply={() => void apply(op)}
            onCheck={() => void check(op)}
          />
        )}
      </div>

      {status.operations.length > 0 && (
        <section>
          <h4 className="mb-1.5 text-meta font-semibold text-text-secondary">{t("microapps.sheets.history")}</h4>
          <ul aria-label={t("microapps.sheets.history")} className="grid gap-1 text-meta text-text-secondary">
            {status.operations.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center gap-2">
                <span>{o.created_at ? formatRelative(o.created_at) : ""}</span>
                <span className="text-text-primary">{t(STATE_LABEL[o.state])}</span>
                <Badge tone={GOOGLE_TONE[o.google_status]}>{t(GOOGLE_LABEL[o.google_status])}</Badge>
                {o.auto ? <span>{t("microapps.sheets.auto.label")}</span> : o.mine && <span>{t("microapps.sheets.mine")}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function SyncError({
  error,
  link,
  isOwner,
  connectHref,
  requesting,
  onRequestAccess,
}: {
  error: unknown;
  link: SheetLink;
  isOwner: boolean;
  connectHref: string;
  requesting: boolean;
  onRequestAccess: () => void;
}) {
  const action = error instanceof ApiError ? error.extra.action : undefined;
  const limit = error instanceof ApiError && ROW_LIMIT_CODES.has(error.code ?? "") && typeof error.extra.limit === "number" ? error.extra.limit : null;
  const missing = extraList(error, "missing");
  const tabs = extraList(error, "tabs");
  const tab = extraString(error, "tab");
  const canAsk = link.account_mode === "per_user" && !isOwner;
  return (
    <div role="alert" className="space-y-2 text-ui text-danger">
      <p>{formatApiError(error)}</p>
      {limit !== null && <p>{tn("microapps.sheets.error.limit", limit)}</p>}
      {tab && <p>{t("microapps.sheets.error.tab", { name: tab })}</p>}
      {missing.length > 0 && <p>{t("microapps.sheets.error.missing", { names: missing.join(", ") })}</p>}
      {tabs.length > 0 && <p>{t("microapps.sheets.error.tabs", { names: tabs.join(", ") })}</p>}
      {action === "connect_google" && (
        <a className={buttonClass("secondary", "sm")} href={connectHref}>
          {t("microapps.sheets.google.connect")}
        </a>
      )}
      {action === "request_access" &&
        (canAsk ? (
          <Button size="sm" variant="secondary" busy={requesting} onClick={onRequestAccess}>
            {t("microapps.sheets.access.request")}
          </Button>
        ) : (
          <p className="text-text-secondary">{t("microapps.sheets.access.shareHint")}</p>
        ))}
    </div>
  );
}

function OperationView({
  op,
  places,
  chosen,
  busy,
  onDecide,
  onApply,
  onCheck,
}: {
  op: SheetOperation;
  places: Places;
  chosen: Record<string, Side>;
  busy: Busy;
  onDecide: (key: string, side: Side) => void;
  onApply: () => void;
  onCheck: () => void;
}) {
  const header: HeaderOf = (collection, field) => op.headers?.[collection]?.[field] ?? field;
  const pending = op.state === "previewed" || op.state === "applying";

  if (op.state === "applied") {
    return (
      <div role="status" className="space-y-2 text-ui">
        <p className="text-text-primary">{t("microapps.sheets.result.app", { n: op.result?.app_changes ?? 0 })}</p>
        <p className={op.google_status === "confirmed" || op.google_status === "none" ? "text-success" : op.google_status === "pending" ? "text-text-secondary" : "text-warning"}>
          {t(`microapps.sheets.result.${op.google_status}` as MessageKey)}
        </p>
        {op.unsettled && (
          <Button size="sm" variant="secondary" busy={busy === "check"} disabled={blocked(busy, "check")} onClick={onCheck}>
            {t("microapps.sheets.sync.check")}
          </Button>
        )}
      </div>
    );
  }
  if (!pending) return <p className="text-ui text-text-secondary">{t("microapps.sheets.result.previewAgain")}</p>;

  const s = op.summary;
  const updates = op.updates ?? [];
  const keys = updates.flatMap((u) => u.conflicts.map((c) => conflictKey(u.record_id, c.field)));
  const undecided = op.state === "previewed" ? keys.filter((k) => !chosen[k]).length : 0;
  const nothing = !s.imports && !s.exports && !s.conflicts;
  // Every conflict needs a decision, so all of them show; plain changes are
  // capped, since a first sync of a large sheet can list thousands.
  const conflicted = updates.filter((u) => u.conflicts.length > 0);
  const plain = updates.filter((u) => u.conflicts.length === 0);
  const shownUpdates = [...conflicted, ...plain.slice(0, LIST_LIMIT)];
  const hiddenUpdates = plain.length - Math.min(plain.length, LIST_LIMIT);

  return (
    <div className="space-y-4">
      <DetailList>
        <DetailItem label={t("microapps.sheets.summary.imports")}>{s.imports ?? 0}</DetailItem>
        <DetailItem label={t("microapps.sheets.summary.exports")}>{s.exports ?? 0}</DetailItem>
        <DetailItem label={t("microapps.sheets.summary.conflicts")}>{s.conflicts ?? 0}</DetailItem>
        <DetailItem label={t("microapps.sheets.summary.issues")}>{s.issues ?? 0}</DetailItem>
      </DetailList>
      {nothing && <p className="text-ui text-text-secondary">{t("microapps.sheets.summary.nothing")}</p>}

      {updates.length > 0 && (
        <ul aria-label={t("microapps.sheets.changes")} className="space-y-3">
          {shownUpdates.map((u) => (
            <UpdateRow key={u.record_id} update={u} opId={op.id} label={placeLabel(u, places)} header={header} editable={op.state === "previewed"} chosen={chosen} onDecide={onDecide} />
          ))}
          {hiddenUpdates > 0 && <li className="text-meta text-text-secondary">{t("microapps.sheets.more", { n: hiddenUpdates })}</li>}
        </ul>
      )}

      <ListSection title={t("microapps.sheets.creates")} items={op.creates ?? []} render={(c) => withPlace(placeLabel(c, places), describe(c.data, (f) => header(c.collection, f)))} />
      <ListSection title={t("microapps.sheets.appends")} items={op.appends ?? []} render={(a) => withPlace(placeLabel(a, places), describe(a.values, (f) => header(a.collection, f)))} />
      <ListSection title={t("microapps.sheets.issues")} items={op.issues ?? []} render={(issue) => issueText(issue, places, header)} tone="text-warning" />

      {/* With nothing to change, applying only remembers values both sides
          already share, so later edits merge without conflicts. */}
      {(!nothing || (s.agreed ?? 0) > 0) && (
        <div className="flex flex-wrap items-center gap-3">
          <Button variant={nothing ? "secondary" : "primary"} busy={busy === "apply"} disabled={undecided > 0 || blocked(busy, "apply")} onClick={onApply}>
            {t(nothing ? "microapps.sheets.sync.remember" : "microapps.sheets.sync.apply")}
          </Button>
          {nothing && <span className="text-meta text-text-secondary">{t("microapps.sheets.sync.rememberHint", { n: s.agreed ?? 0 })}</span>}
          {undecided > 0 && <span className="text-meta text-text-secondary">{t("microapps.sheets.undecided", { n: undecided })}</span>}
        </div>
      )}
    </div>
  );
}

interface UpdateRowProps {
  update: SheetUpdate;
  opId: string;
  label: string;
  header: HeaderOf;
  editable: boolean;
  chosen: Record<string, Side>;
  onDecide: (key: string, side: Side) => void;
}

/** One record's changes and its conflict choices. Memoized on its own
 * choices, so deciding one conflict redraws one row, not thousands. */
const UpdateRow = memo(function UpdateRow({ update: u, opId, label, header: headerOf, editable, chosen, onDecide }: UpdateRowProps) {
  const header = (field: string) => headerOf(u.collection, field);
  return (
    <li className="rounded-control border border-border p-3 text-ui">
      <p className="mb-1 font-medium text-text-primary">{label}</p>
      <ValueList title={t("microapps.sheets.toApp")} values={u.import} header={header} />
      <ValueList title={t("microapps.sheets.toSheet")} values={u.export} header={header} />
      {u.conflicts.map((c) => {
        const key = conflictKey(u.record_id, c.field);
        return (
          <fieldset key={key} className="mt-2 space-y-1">
            <legend className="text-warning">{t("microapps.sheets.conflict", { header: header(c.field) })}</legend>
            {(["app", "sheet"] as const).map((side) => (
              <label key={side} className="flex items-start gap-2">
                <input
                  type="radio"
                  name={`conflict-${opId}-${key}`}
                  className="size-4 shrink-0 translate-y-0.5 accent-accent"
                  checked={chosen[key] === side}
                  disabled={!editable}
                  onChange={() => onDecide(key, side)}
                />
                <span>
                  {t(side === "app" ? "microapps.sheets.keepApp" : "microapps.sheets.takeSheet", {
                    value: formatValue(side === "app" ? c.app : c.sheet),
                  })}
                </span>
              </label>
            ))}
          </fieldset>
        );
      })}
    </li>
  );
}, sameRow);

function sameRow(a: UpdateRowProps, b: UpdateRowProps): boolean {
  if (a.update !== b.update || a.opId !== b.opId || a.label !== b.label || a.editable !== b.editable || a.onDecide !== b.onDecide) return false;
  return a.update.conflicts.every((c) => {
    const key = conflictKey(a.update.record_id, c.field);
    return a.chosen[key] === b.chosen[key];
  });
}

function describe(values: Record<string, unknown>, header: (field: string) => string): string {
  return Object.entries(values)
    .map(([field, value]) => `${header(field)}: ${formatValue(value)}`)
    .join("; ");
}

const withPlace = (place: string, text: string) => (place ? `${place}: ${text}` : text);

function ValueList({
  title,
  values,
  header,
}: {
  title: string;
  values: Record<string, unknown>;
  header: (field: string) => string;
}) {
  const entries = Object.entries(values);
  if (entries.length === 0) return null;
  return (
    <p className="text-text-secondary">
      {title}: <span className="text-text-primary">{describe(values, header)}</span>
    </p>
  );
}

const LIST_LIMIT = 100;

/** Another action is running: this one waits. */
const blocked = (busy: string | null, action: string) => busy !== null && busy !== action;

/** A titled list of at most LIST_LIMIT lines, then how many more there are. */
function ListSection<T>({ title, items, render, tone = "" }: { title: string; items: T[]; render: (item: T) => string; tone?: string }) {
  if (items.length === 0) return null;
  const hidden = items.length - Math.min(items.length, LIST_LIMIT);
  return (
    <section>
      <h4 className="mb-1 text-meta font-semibold text-text-secondary">{title}</h4>
      <ul className={`grid gap-1 text-ui ${tone}`}>
        {items.slice(0, LIST_LIMIT).map((item, i) => (
          <li key={i}>{render(item)}</li>
        ))}
        {hidden > 0 && <li className="text-meta text-text-secondary">{t("microapps.sheets.more", { n: hidden })}</li>}
      </ul>
    </section>
  );
}

function issueText(issue: SheetIssue, places: Places, headerOf: HeaderOf): string {
  // The row is in the issue's own text; the place adds the collection and tab.
  const place = placeLabel({ collection: issue.collection, tab: issue.tab }, places);
  return withPlace(place, issueBody(issue, places, (field) => headerOf(issue.collection, field)));
}

function issueBody(issue: SheetIssue, places: Places, header: (field: string) => string): string {
  const row = issue.row ?? 0;
  switch (issue.kind) {
    case "invalid_value":
      return t("microapps.sheets.issue.invalid_value", { row, header: header(issue.field ?? "") });
    case "duplicate_key": {
      const first =
        places.tabs && issue.first_tab
          ? t("microapps.sheets.issue.firstRowIn", { tab: issue.first_tab, row: issue.first_row ?? 0 })
          : t("microapps.sheets.issue.firstRow", { row: issue.first_row ?? 0 });
      return t("microapps.sheets.issue.duplicate_key", { row, first });
    }
    case "record_not_in_app":
      return t("microapps.sheets.issue.record_not_in_app", { row });
    case "unmatched_row":
      return t("microapps.sheets.issue.unmatched_row", { row });
    case "missing_required":
      return t("microapps.sheets.issue.missing_required", { row, fields: (issue.fields ?? []).map(header).join(", ") });
    case "removed_from_sheet":
      return t("microapps.sheets.issue.removed_from_sheet", { id: issue.record_id ?? "" });
    case "not_editable":
      return t("microapps.sheets.issue.not_editable", { row, fields: (issue.fields ?? []).map(header).join(", ") });
    case "key_missing":
      return t("microapps.sheets.issue.key_missing", { id: issue.record_id ?? "" });
  }
}
