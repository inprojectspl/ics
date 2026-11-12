import type { MicroApp, MicroAppAction } from "../../api/microApplications";
import { formatBytes, formatRelative } from "../../lib/format";
import { t, type MessageKey } from "../../lib/i18n";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { DetailItem, DetailList } from "../ui/DetailList";
import { PanelSection } from "../ui/PanelSection";
import { useMicroAppControl } from "./useMicroAppControl";

const STATE_LABEL: Record<string, MessageKey> = {
  sleeping: "microapps.state.sleeping",
  ready: "microapps.state.ready",
  running: "microapps.state.running",
  draining: "microapps.state.draining",
  suspended: "microapps.state.suspended",
  unknown: "microapps.state.unknown",
};

/** The App tab: what the app runs, in which state, how much data it holds
 * and, for `app.control`, the switches. */
export function MicroAppOverview({ app }: { app: MicroApp }) {
  const rt = app.runtime;
  const suspended = app.desired_state === "suspended";
  const releaseBehind = app.active_release && app.active_release.package_version !== app.package_version;
  const { run, busy, error } = useMicroAppControl(app);
  const control = (action: MicroAppAction) => (
    <Button
      key={action}
      size="sm"
      variant={action === "suspend" ? "danger" : "secondary"}
      busy={busy === action}
      disabled={busy !== null && busy !== action}
      onClick={() => void run(action)}
      data-action={action}
    >
      {t(`microapps.action.${action}` as MessageKey)}
    </Button>
  );

  return (
    <div className="grid gap-6">
      <DetailList>
        <DetailItem label={t("microapps.field.state")}>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={suspended ? "warning" : "success"}>
              <span data-field="desired-state">{suspended ? t("microapps.desired.suspended") : t("microapps.desired.enabled")}</span>
            </Badge>
            <span data-field="runtime-state">
              {t(STATE_LABEL[rt.state] ?? "microapps.state.unknown")}
              {rt.inflight > 0 ? ` · ${t("microapps.inflight", { n: rt.inflight })}` : ""}
            </span>
          </div>
          {rt.sampled_at && (
            <div className="text-meta text-text-tertiary">{t("microapps.sampled", { when: formatRelative(rt.sampled_at) })}</div>
          )}
        </DetailItem>
        <DetailItem label={t("microapps.field.release")}>
          {app.active_release ? (
            <>
              <div>{t("microapps.activeRelease", { version: app.active_release.package_version })}</div>
              <div className="font-code text-meta text-text-tertiary">{app.active_release.digest.slice(7, 19)}</div>
            </>
          ) : (
            <div className="text-text-secondary">{t("microapps.noRelease")}</div>
          )}
          {releaseBehind && <div className="text-meta text-warning">{t("microapps.packageNewer", { version: app.package_version })}</div>}
          {app.last_publication && app.last_publication.status !== "succeeded" && (
            <div className={app.last_publication.status === "failed" ? "text-meta text-danger" : "text-meta text-text-secondary"}>
              {t("microapps.lastPublication", { status: app.last_publication.status, step: app.last_publication.step })}
              {app.last_publication.error_code ? ` (${app.last_publication.error_code})` : ""}
            </div>
          )}
        </DetailItem>
        <DetailItem label={t("microapps.field.data")}>
          {app.data.measured ? (
            <>
              <div>{formatBytes(app.data.bytes)}</div>
              <div className="text-meta text-text-secondary">
                {t("microapps.rows", { rows: app.data.rows_estimate ?? 0, tables: app.data.tables ?? 0 })}
              </div>
            </>
          ) : (
            <div className="text-text-secondary">{t("microapps.notMeasured")}</div>
          )}
          <div className="text-meta text-text-tertiary">{t("microapps.schema", { version: app.data.schema_version })}</div>
        </DetailItem>
        <DetailItem label={t("microapps.field.usage")}>
          {rt.last_used_at ? t("microapps.lastUsed", { when: formatRelative(rt.last_used_at) }) : t("microapps.neverUsed")}
          {rt.last_error && (
            <div className="text-meta text-danger">
              {t("microapps.lastError", { code: rt.last_error.code })}
              {rt.last_error.at ? ` · ${formatRelative(rt.last_error.at)}` : ""}
            </div>
          )}
        </DetailItem>
      </DetailList>
      {app.rights.control && (
        <PanelSection title={t("microapps.field.controls")} last>
          {error && (
            <p role="alert" className="mb-2 text-meta text-danger">
              {error}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {suspended ? control("enable") : [control("sleep"), control("restart"), control("suspend")]}
          </div>
        </PanelSection>
      )}
    </div>
  );
}
