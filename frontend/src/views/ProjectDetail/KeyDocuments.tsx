import { FormEvent, useCallback, useState } from "react";
import { ArrowDown, ArrowUp, BookMarked, X } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type KeyDocument } from "../../api";
import { FreshnessBadge } from "../../components/AssetMetaBadges";
import { INPUT_CLASS, inputClass } from "../../components/Field";
import { AppLink } from "../../components/ui/AppLink";
import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { qk } from "../../lib/queries";

interface Props {
  slug: string;
  canEdit: boolean;
}

type Entry = { asset_id: string; reason: string | null };

const SEARCH_LIMIT = 10;

const entriesOf = (docs: KeyDocument[]): Entry[] =>
  docs.map((d) => ({ asset_id: d.asset_id, reason: d.reason }));

/** Moves the item at `from` by `delta` places; out-of-range moves return the list unchanged. */
export function moveItem<T>(list: readonly T[], from: number, delta: number): T[] {
  const to = from + delta;
  const next = [...list];
  const item = next[from];
  if (item === undefined || to < 0 || to >= next.length) return next;
  next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

/**
 * The project's ordered reading list for people and agents (ADR-0018):
 * owners reorder, annotate, add and remove; members only read it.
 */
export function KeyDocuments({ slug, canEdit }: Props) {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: qk.keyDocuments(slug), queryFn: () => api.getKeyDocuments(slug) });
  const docs = list.data ?? null;
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  // The search runs on submit, not while typing.
  const [term, setTerm] = useState("");
  const search = useQuery({
    queryKey: qk.assetSearch(term, SEARCH_LIMIT),
    queryFn: () => api.searchAssets(term, SEARCH_LIMIT),
    enabled: term.length >= 2,
  });
  const results = search.data ?? null;
  const [busy, setBusy] = useState(false);
  const [actionError, setError] = useState<string | null>(null);
  const loadError = list.error ?? search.error;
  const error = actionError ?? (loadError ? formatApiError(loadError) : null);

  const save = useCallback(
    async (entries: Entry[]) => {
      setBusy(true);
      setError(null);
      try {
        queryClient.setQueryData(qk.keyDocuments(slug), await api.putKeyDocuments(slug, entries));
        setReasons({});
      } catch (e) {
        setError(formatApiError(e));
      } finally {
        setBusy(false);
      }
    },
    [slug, queryClient],
  );

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (q.length < 2) return;
    setTerm(q);
    // The same term again is a fresh search, as a click on the button was before.
    if (q === term) void search.refetch();
  };

  const entries = docs ? entriesOf(docs) : [];
  const present = new Set(entries.map((e) => e.asset_id));

  return (
    <SettingsSection id="project-key-documents" title={t("projectLinks.keyTitle")} intro={t("projectLinks.keyIntro")}>
      {docs === null && !error && <p className="text-meta text-text-secondary">{t("common.loading")}</p>}
      {docs !== null && docs.length === 0 && (
        <p className="text-ui text-text-secondary">{t("projectLinks.keyEmpty")}</p>
      )}
      {docs !== null && docs.length > 0 && (
        <ol className="divide-y divide-border rounded-card border border-border" aria-label={t("projectLinks.keyTitle")}>
          {docs.map((d, i) => {
            const title = d.title ?? d.slug;
            return (
              <li key={d.asset_id} className="px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="w-5 text-meta tabular-nums text-text-secondary">{i + 1}.</span>
                  <AppLink href={`/v/${d.slug}`} className="min-w-0 flex-1 truncate text-ui font-medium text-text-primary hover:text-accent">
                    {title}
                  </AppLink>
                  <FreshnessBadge freshness={d.freshness} />
                  {canEdit && (
                    <span className="flex items-center gap-0.5 shrink-0">
                      <IconButton
                        size="sm"
                        label={t("projectLinks.moveUp", { title })}
                        disabled={busy || i === 0}
                        onClick={() => void save(moveItem(entries, i, -1))}
                        icon={<ArrowUp size={14} aria-hidden />}
                      />
                      <IconButton
                        size="sm"
                        label={t("projectLinks.moveDown", { title })}
                        disabled={busy || i === docs.length - 1}
                        onClick={() => void save(moveItem(entries, i, 1))}
                        icon={<ArrowDown size={14} aria-hidden />}
                      />
                      <IconButton
                        size="sm"
                        label={t("projectLinks.remove", { title })}
                        disabled={busy}
                        onClick={() => void save(entries.filter((e) => e.asset_id !== d.asset_id))}
                        icon={<X size={14} aria-hidden />}
                      />
                    </span>
                  )}
                </div>
                {canEdit ? (
                  <input
                    value={reasons[d.asset_id] ?? d.reason ?? ""}
                    maxLength={300}
                    aria-label={t("projectLinks.reasonLabel", { title })}
                    placeholder={t("projectLinks.reasonPlaceholder")}
                    onChange={(e) => setReasons((r) => ({ ...r, [d.asset_id]: e.target.value }))}
                    onBlur={() => {
                      const next = reasons[d.asset_id];
                      if (next === undefined || next.trim() === (d.reason ?? "")) return;
                      void save(
                        entries.map((e) =>
                          e.asset_id === d.asset_id ? { ...e, reason: next.trim() || null } : e,
                        ),
                      );
                    }}
                    className={`${inputClass({ size: "sm", full: false })} mt-2 ml-7 w-[calc(100%-1.75rem)]`}
                  />
                ) : (
                  d.reason && <p className="ml-7 mt-0.5 text-meta text-text-secondary">{d.reason}</p>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {canEdit && docs !== null && (
        <div className="mt-4 max-w-xl">
          <form onSubmit={onSearch} className="flex gap-2" role="search">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label={t("projectLinks.searchLabel")}
              placeholder={t("projectLinks.searchLabel")}
              className={`${INPUT_CLASS} flex-1`}
            />
            <Button type="submit" variant="secondary" disabled={query.trim().length < 2}>
              {t("projectLinks.search")}
            </Button>
          </form>
          {results && (
            <ul className="mt-2 space-y-1" aria-label={t("projectLinks.searchResults")}>
              {results.filter((a) => !present.has(a.id)).map((a) => (
                <li key={a.id} className="flex items-center gap-2 rounded-control px-2 py-1 text-ui hover:bg-surface-hover">
                  <span className="flex-1 min-w-0 truncate text-text-primary">{a.title ?? a.slug}</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => void save([...entries, { asset_id: a.id, reason: null }])}
                  >
                    {t("common.add")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-meta text-danger mt-2">
          {error}
        </p>
      )}
    </SettingsSection>
  );
}

/** A titled block of the project settings. */
export function SettingsSection({
  id,
  title,
  intro,
  children,
}: {
  id: string;
  title: string;
  intro: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="rounded-card border border-border bg-surface p-4 shadow-card sm:p-5">
      <h2 id={id} className="text-body font-semibold text-text-primary">
        {title}
      </h2>
      <p className="mb-4 mt-0.5 text-ui text-text-secondary">{intro}</p>
      {children}
    </section>
  );
}

/** The key documents as the first thing on the project's document tab:
 * where to start reading, in order. Read-only; owners edit it in Settings. */
export function KeyDocumentsList({ docs }: { docs: readonly KeyDocument[] }) {
  return (
    <section aria-labelledby="project-key-list" className="rounded-card border border-border bg-surface shadow-card">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <BookMarked size={16} aria-hidden className="text-accent" />
        <h2 id="project-key-list" className="text-ui font-semibold text-text-primary">
          {t("projectLinks.keyTitle")}
        </h2>
        <span className="text-meta text-text-secondary">{t("projectLinks.keyShort")}</span>
      </div>
      <ol className="grid gap-px bg-border sm:grid-cols-2 xl:grid-cols-3">
        {docs.map((d, i) => (
          <li key={d.asset_id} className="relative flex gap-3 bg-surface px-4 py-3 hover:bg-surface-subtle">
            <span className="text-meta font-medium tabular-nums text-text-secondary">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <AppLink
                href={`/v/${d.slug}`}
                className="line-clamp-2 text-ui font-medium text-text-primary after:absolute after:inset-0 hover:text-accent"
              >
                {d.title ?? d.slug}
              </AppLink>
              {d.reason && <p className="mt-0.5 line-clamp-2 text-meta text-text-secondary">{d.reason}</p>}
            </div>
            <FreshnessBadge freshness={d.freshness} />
          </li>
        ))}
      </ol>
    </section>
  );
}
