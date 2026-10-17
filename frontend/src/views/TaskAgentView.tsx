import { useCallback, useEffect, useState } from "react";

import { api, type ContextPack, type Me } from "../api";
import { contextPackQuery } from "../api/relations";
import { LoadingListSkeleton } from "../components/LoadingListSkeleton";
import { ProjectFrame } from "../components/projects/ProjectFrame";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { ContextPackView } from "./taskAgent/ContextPackView";
import { readParams, toQuery, toSearch, type TaskAgentParams } from "./taskAgent/params";
import { TaskAgentForm } from "./taskAgent/TaskAgentForm";

interface Props {
  me: Me;
  slug: string;
}

type Loaded = { key: string; data: ContextPack } | { key: string; error: string };

/**
 * Task agent view (`/projects/<slug>/agent?wp=...`): the context pack an
 * agent gets for one task from `GET /api/context`, to debug why it did or
 * did not read a document. The form lives in the query string.
 */
export function TaskAgentView({ me, slug }: Props) {
  const [params, setParams] = useState<TaskAgentParams>(() =>
    readParams(new URLSearchParams(window.location.search), slug),
  );
  // Bumped on every submit, so asking again with the same params refetches.
  const [run, setRun] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const query = params.wp ? contextPackQuery(toQuery(params)) : null;
  const key = `${query}|${run}`;

  useEffect(() => {
    if (!params.wp) return;
    let cancelled = false;
    api.getContextPack(toQuery(params)).then(
      (data) => !cancelled && setLoaded({ key, data }),
      (e) => !cancelled && setLoaded({ key, error: formatApiError(e) }),
    );
    return () => {
      cancelled = true;
    };
  }, [params, key]);

  const submit = useCallback(
    (next: TaskAgentParams) => {
      const qs = toSearch(next, slug);
      window.history.replaceState({}, "", `/projects/${slug}/agent${qs ? `?${qs}` : ""}`);
      setParams(next);
      setRun((n) => n + 1);
    },
    [slug],
  );

  const current = loaded?.key === key ? loaded : null;
  const pack = current && "data" in current ? current.data : null;
  const error = current && "error" in current ? current.error : null;

  return (
    <ProjectFrame me={me} slug={slug} tab="agent">
      <p className="mb-5 max-w-3xl text-ui text-text-secondary">{t("taskAgent.description")}</p>
      <TaskAgentForm key={toSearch(params, slug)} slug={slug} params={params} onSubmit={submit} />
      {query && (
        <p className="mb-6 overflow-x-auto whitespace-nowrap font-code text-meta text-text-secondary">
          GET /api/context?{query}
        </p>
      )}
      {!query ? (
        <p className="text-ui text-text-secondary">{t("taskAgent.start")}</p>
      ) : error ? (
        <p role="alert" className="text-ui text-danger">
          {error}
        </p>
      ) : pack ? (
        <ContextPackView pack={pack} budget={params.budget} />
      ) : (
        <LoadingListSkeleton rows={4} />
      )}
    </ProjectFrame>
  );
}
