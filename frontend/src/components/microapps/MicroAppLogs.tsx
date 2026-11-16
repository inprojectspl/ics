import { useQuery } from "@tanstack/react-query";

import { listLogs } from "../../api/microApplications";
import { formatApiError } from "../../lib/apiError";
import { formatRelative } from "../../lib/format";
import { t } from "../../lib/i18n";

/** The Logs tab: recent lines of the app and its runtime, newest first. */
export function MicroAppLogs({ assetId }: { assetId: string }) {
  const logs = useQuery({ queryKey: ["microapps", assetId, "logs"], queryFn: () => listLogs(assetId), refetchInterval: 10000 });
  const items = logs.data?.items ?? [];
  if (logs.error) return <p role="alert" className="text-ui text-danger">{formatApiError(logs.error)}</p>;
  if (logs.isLoading) return <p className="text-meta text-text-tertiary">{t("common.loading")}</p>;
  if (items.length === 0) return <p className="text-ui text-text-secondary">{t("microapps.logsEmpty")}</p>;
  return (
    <ul aria-label={t("microapps.logsTitle")} className="grid gap-1 font-code text-meta">
      {items.map((l) => (
        <li key={l.id} className={l.level === "error" ? "text-danger" : "text-text-secondary"}>
          {l.ts ? formatRelative(l.ts) : ""} · {l.source} · {l.message}
        </li>
      ))}
    </ul>
  );
}
