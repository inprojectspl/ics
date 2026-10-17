import { useCallback, useState } from "react";
import { ShieldOff, Sparkles } from "lucide-react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type HygieneList, type Me } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import { LoadingListSkeleton } from "../components/LoadingListSkeleton";
import { EmptyState } from "../components/EmptyState";
import { Pagination } from "../components/Pagination";
import { ProjectFrame } from "../components/projects/ProjectFrame";
import { useToast } from "../components/Toast";
import { ChipTabs } from "../components/ui/ChipTabs";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { qk } from "../lib/queries";
import { useDocTypes } from "../lib/useDocTypes";
import { DuplicateRow } from "./hygiene/DuplicateRow";
import { HygieneRow } from "./hygiene/HygieneRow";
import { HYGIENE_LISTS, listInfo, parseHygieneList } from "./hygiene/lists";

interface Props {
  me: Me;
  slug: string;
}

interface Query {
  list: HygieneList;
  page: number;
}

function initialQuery(): Query {
  const params = new URLSearchParams(window.location.search);
  const page = Number(params.get("page"));
  return { list: parseHygieneList(params.get("list")), page: Number.isInteger(page) && page > 1 ? page : 1 };
}

/** Documents of a project that need attention, list by list (owners and editors). */
export function ProjectHygiene({ me, slug }: Props) {
  const docTypes = useDocTypes();
  const { toast } = useToast();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState<Query>(initialQuery);
  const hygiene = useQuery({
    queryKey: qk.projectHygiene(slug, query.list, query.page),
    queryFn: () => api.getProjectHygiene(slug, query.list, query.page),
    // The previous result stays on screen while the next one loads, so the
    // list does not flash after every fix or list switch.
    placeholderData: keepPreviousData,
  });

  const go = useCallback(
    (next: Query) => {
      const qs = new URLSearchParams({ list: next.list });
      if (next.page > 1) qs.set("page", String(next.page));
      window.history.replaceState({}, "", `/projects/${slug}/hygiene?${qs.toString()}`);
      setQuery(next);
    },
    [slug],
  );
  const onDone = useCallback(
    (message: string) => {
      toast(message, "success");
      // Every list and page: a fix changes the counters of the others too.
      void queryClient.invalidateQueries({ queryKey: qk.projectHygiene(slug) });
    },
    [toast, queryClient, slug],
  );
  const onError = useCallback((message: string) => toast(message, "error"), [toast]);

  const data = hygiene.data ?? null;
  const error = hygiene.error ? formatApiError(hygiene.error) : null;
  const stale = hygiene.isFetching;
  const shown = data && data.list === query.list && data.project.slug === slug ? data : null;
  const info = listInfo(query.list);

  const counters = data?.counters ?? {};
  const lists = HYGIENE_LISTS.filter((l) => !l.optional || counters[l.key] !== undefined);

  return (
    <ProjectFrame me={me} slug={slug} tab="hygiene">
      {error ? (
        <EmptyState icon={ShieldOff} title={t("viewerStates.noAccess")} description={error} />
      ) : (
        <>
          <ChipTabs
            label={t("hygiene.lists")}
            items={lists.map((l) => ({ key: l.key, label: t(l.label), count: counters[l.key] ?? 0 }))}
            active={query.list}
            onChange={(list) => go({ list, page: 1 })}
          />
          <p className="mt-4 max-w-3xl text-ui text-text-secondary">{t(info.hint)}</p>
          <div className="mt-4">
            {!shown ? (
              <LoadingListSkeleton rows={4} />
            ) : shown.items.length === 0 ? (
              <EmptyState icon={Sparkles} title={t("hygiene.empty")} />
            ) : (
              <ul className="space-y-2" aria-busy={stale || undefined} aria-label={t(info.label)}>
                {shown.items.map((item) =>
                  "a" in item ? (
                    <DuplicateRow key={`${item.a.id}|${item.b.id}`} slug={slug} pair={item} onDone={onDone} onError={onError} />
                  ) : (
                    <HygieneRow
                      key={item.id}
                      item={item}
                      list={shown.list}
                      docTypes={docTypes}
                      onDone={onDone}
                      onError={onError}
                      confirm={confirm}
                    />
                  ),
                )}
              </ul>
            )}
            {shown && (
              <Pagination page={shown.page} pageSize={shown.page_size} total={shown.total} onPage={(page) => go({ list: query.list, page })} />
            )}
          </div>
        </>
      )}
    </ProjectFrame>
  );
}
