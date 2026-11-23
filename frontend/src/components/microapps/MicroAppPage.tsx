import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { getMicroApp, type MicroApp } from "../../api/microApplications";
import { formatApiError } from "../../lib/apiError";
import { t, type MessageKey } from "../../lib/i18n";
import { useLocation } from "../../lib/useLocation";
import { mt } from "../../styles/markdown-theme";
import { PageTabs } from "../PageTabs";
import { buttonClass } from "../ui/Button";
import { MicroAppAccess } from "./MicroAppAccess";
import { MicroAppData } from "./MicroAppData";
import { MicroAppLogs } from "./MicroAppLogs";
import { MicroAppOverview } from "./MicroAppOverview";
import { MicroAppSheets } from "./MicroAppSheets";
import { microAppKey } from "./useMicroAppControl";

type Tab = "app" | "data" | "access" | "sheets" | "logs";

const TABS: ReadonlyArray<{ key: Tab; label: MessageKey; allowed: (app: MicroApp) => boolean }> = [
  { key: "app", label: "microapps.tab.app", allowed: () => true },
  { key: "data", label: "microapps.tab.data", allowed: () => true },
  { key: "access", label: "microapps.tab.access", allowed: (a) => a.rights.manage_access },
  // Configuring the link needs manage_access, running the sync control.
  { key: "sheets", label: "microapps.tab.sheets", allowed: (a) => a.rights.control || a.rights.manage_access },
  // The same rights as the logs endpoint.
  { key: "logs", label: "microapps.tab.logs", allowed: (a) => a.rights.control || a.rights.publish },
];

/**
 * The reader body of a micro-application. The app itself runs on its own
 * origin; nothing of its package is loaded or evaluated in the ICS panel.
 * Tabs are links (`?tab=`), so each section has its own address.
 */
export function MicroAppPage({ assetId, title, base }: { assetId: string; title: string; base: string }) {
  const app = useQuery({
    queryKey: microAppKey(assetId),
    queryFn: () => getMicroApp(assetId),
    // Faster while something is moving, so a drain or a wake-up shows within
    // seconds. Reading the state never wakes the app.
    refetchInterval: (query) => {
      const a = query.state.data;
      return a && (a.runtime.state === "running" || a.runtime.state === "draining" || a.last_publication?.status === "running")
        ? 2000
        : 10000;
    },
  });
  const requested = useLocation().search.get("tab");
  const a = app.data;
  const tabs = a ? TABS.filter((x) => x.allowed(a)) : [];
  const tab = tabs.find((x) => x.key === requested)?.key ?? "app";
  const canOpen = a && a.rights.use && a.active_release && a.desired_state === "enabled";

  const column = "max-w-(--reading-width) mx-auto px-(--gutter)";
  const tabsNav = a && (
    <PageTabs
      tabs={tabs.map((x) => ({ key: x.key, href: x.key === "app" ? base : `${base}?tab=${x.key}`, label: t(x.label) }))}
      active={tab}
      ariaLabel={t("microapps.tabs")}
    />
  );

  // Laid out like an HTML bundle: the title, what this is, the way in; then
  // the sections. The Data tab is a Markdown document with its own column.
  return (
    <>
      <div className={`${column} pt-16`}>
        <h1 className={mt.title}>{title}</h1>
        <p className="text-text-secondary text-body mb-8 mt-4">{a?.description ?? t("microapps.landingHint")}</p>
        {canOpen && (
          <div className="flex flex-wrap items-center gap-3 mb-10">
            <a className={buttonClass("primary", "lg")} href={a.app_url} target="_blank" rel="noopener" data-action="open">
              {t("microapps.action.open")}
              <ExternalLink size={16} aria-hidden />
            </a>
          </div>
        )}
        {app.error && <p role="alert" className="text-ui text-danger mb-6">{formatApiError(app.error)}</p>}
        {tabsNav}
      </div>
      {a && tab === "data" ? (
        <MicroAppData assetId={assetId} />
      ) : (
        a && (
          <div className={`${column} pt-8 pb-16`}>
            {tab === "app" && <MicroAppOverview app={a} />}
            {tab === "access" && <MicroAppAccess assetId={assetId} />}
            {tab === "sheets" && <MicroAppSheets assetId={assetId} base={base} />}
            {tab === "logs" && <MicroAppLogs assetId={assetId} />}
          </div>
        )
      )}
    </>
  );
}
