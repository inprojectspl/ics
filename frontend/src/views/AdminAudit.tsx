import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { ScrollText } from "lucide-react";
import { api, AuditEntry, Me } from "../api";
import { AdminPage } from "../components/AdminPage";
import { EmptyState } from "../components/EmptyState";
import { INPUT_CLASS } from "../components/Field";
import { LoadingListSkeleton } from "../components/LoadingListSkeleton";
import { SearchInput } from "../components/SearchInput";
import { Button } from "../components/ui/Button";
import { PageHeader } from "../components/ui/PageHeader";
import { formatApiError } from "../lib/apiError";
import { formatDay } from "../lib/format";
import { nameCollator, t, tn } from "../lib/i18n";
import { useDebouncedValue } from "../lib/useDebouncedValue";
import { AUDIT_CATEGORIES, CATEGORY_LABEL, actionLabel, auditCategory } from "./adminAudit/auditActions";
import { AuditRow } from "./adminAudit/AuditRow";

interface Props {
  me: Me;
}

const PAGE = 50;

export function AdminAudit({ me }: Props) {
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [target, setTarget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [knownActions, setKnownActions] = useState<string[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const inflight = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api.listAuditActions().then(setKnownActions).catch(() => setKnownActions([]));
  }, []);

  // Both free-text filters fire a fetch on change; debounce keeps a typed
  // word from costing one request per character.
  const debouncedActor = useDebouncedValue(actor);
  const debouncedTarget = useDebouncedValue(target);

  const load = useCallback(
    async (replace: boolean) => {
      // A newer request (filter change) wins: an older response arriving
      // late must not overwrite it.
      inflight.current?.abort();
      const controller = new AbortController();
      inflight.current = controller;
      setLoading(true);
      setError(null);
      try {
        const page = await api.listAudit(
          {
            action: action || undefined,
            actor: debouncedActor || undefined,
            target: debouncedTarget || undefined,
            before_id: replace ? undefined : cursor || undefined,
            limit: PAGE,
          },
          controller.signal,
        );
        setItems((prev) => (replace ? page.items : [...prev, ...page.items]));
        setCursor(page.next_cursor);
      } catch (e) {
        if (controller.signal.aborted) return;
        setError(formatApiError(e));
      } finally {
        if (inflight.current === controller) setLoading(false);
      }
    },
    [action, debouncedActor, debouncedTarget, cursor],
  );

  useEffect(() => {
    void load(true);
    // Reload from the first page when a filter changes; `load` also depends
    // on the cursor, and following it here would reset "load more".
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action, debouncedActor, debouncedTarget]);

  useEffect(() => () => inflight.current?.abort(), []);

  const toggle = useCallback((id: number) => setOpenId((cur) => (cur === id ? null : id)), []);
  const rows = useMemo(() => flattenByDay(items), [items]);
  // The log grows by 50 rows per "load older"; only rows near the viewport
  // are mounted so long sessions stay responsive. Rows are measured, so an
  // opened one takes the room it needs.
  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: (i) => (rows[i]?.kind === "day" ? 36 : 60),
    overscan: 12,
    scrollMargin: listRef.current?.offsetTop ?? 0,
  });

  const grouped = useMemo(() => groupActions(knownActions), [knownActions]);

  return (
    <AdminPage me={me} tab="audit">
      <PageHeader title={t("adminAudit.title")} description={t("adminAudit.intro")} />

      <div
        role="search"
        aria-label={t("adminAudit.filters")}
        className="mb-4 grid gap-2 sm:grid-cols-[minmax(0,16rem)_minmax(0,1fr)_minmax(0,1fr)]"
      >
        <select
          aria-label={t("adminAudit.action")}
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className={INPUT_CLASS}
        >
          <option value="">{t("adminAudit.allActions")}</option>
          {grouped.map(([category, actions]) => (
            <optgroup key={category} label={t(CATEGORY_LABEL[category])}>
              {actions.map((a) => (
                <option key={a.code} value={a.code}>
                  {a.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <SearchInput value={actor} onChange={setActor} ariaLabel={t("adminAudit.actor")} placeholder={t("adminAudit.actorPlaceholder")} />
        <SearchInput value={target} onChange={setTarget} ariaLabel={t("adminAudit.target")} placeholder={t("adminAudit.targetPlaceholder")} />
      </div>

      {error && (
        <p role="alert" className="mb-4 text-ui text-danger">
          {error}
        </p>
      )}

      {rows.length === 0 && loading && <LoadingListSkeleton rows={6} />}
      {rows.length === 0 && !loading && !error && (
        <EmptyState icon={ScrollText} title={t("adminAudit.emptyTitle")} description={t("adminAudit.empty")} />
      )}

      {rows.length > 0 && (
        <div className="overflow-hidden rounded-card border border-border bg-surface shadow-card">
          <div
            ref={listRef}
            role="list"
            aria-label={t("adminAudit.title")}
            className="relative"
            style={{ height: virtualizer.getTotalSize() }}
          >
            {virtualizer.getVirtualItems().map((v) => {
              const row = rows[v.index];
              if (!row) return null;
              return (
                <div
                  key={v.key}
                  role="listitem"
                  data-index={v.index}
                  ref={virtualizer.measureElement}
                  className="absolute inset-x-0"
                  style={{ transform: `translateY(${v.start - virtualizer.options.scrollMargin}px)` }}
                >
                  {row.kind === "day" ? (
                    <h2 className="flex items-baseline justify-between gap-3 border-b border-border bg-surface-subtle px-3 py-2 text-meta font-semibold text-text-secondary sm:px-4">
                      {row.day}
                      <span className="font-normal tabular-nums">{tn("adminAudit.eventCount", row.count)}</span>
                    </h2>
                  ) : (
                    <AuditRow entry={row.entry} open={openId === row.entry.id} onToggle={toggle} />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {cursor !== null && (
        <div className="mt-6 flex justify-center">
          <Button variant="secondary" onClick={() => void load(false)} busy={loading}>
            {t("adminAudit.loadOlder")}
          </Button>
        </div>
      )}
    </AdminPage>
  );
}

/** The filter's actions under their categories, each sorted by its label. */
function groupActions(actions: readonly string[]) {
  const byName = nameCollator();
  const labelled = actions.map((code) => ({ code, label: actionLabel(code), category: auditCategory(code) }));
  labelled.sort((a, b) => byName.compare(a.label, b.label));
  return AUDIT_CATEGORIES.map((c) => [c, labelled.filter((a) => a.category === c)] as const).filter(([, list]) => list.length > 0);
}

type AuditListRow = { kind: "day"; day: string; count: number } | { kind: "event"; entry: AuditEntry };

/** Day headers interleaved with events, flat so the list can be virtualized. */
export function flattenByDay(items: AuditEntry[]): AuditListRow[] {
  const out: AuditListRow[] = [];
  let header: { kind: "day"; day: string; count: number } | null = null;
  for (const entry of items) {
    const day = formatDay(entry.timestamp);
    if (!header || header.day !== day) {
      header = { kind: "day", day, count: 0 };
      out.push(header);
    }
    header.count++;
    out.push({ kind: "event", entry });
  }
  return out;
}
