import { useEffect, useState } from "react";
import { queryOptions, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import {
  disconnectGoogle,
  getSheetStatus,
  googleConnectUrl,
  removeSheetLink,
  type SheetColumnOwner,
  type SheetLink,
  type SheetStatus,
} from "../../api/sheets";
import { formatApiError } from "../../lib/apiError";
import { messageForCode } from "../../lib/errorMessages";
import { formatRelative } from "../../lib/format";
import { t, tn, type MessageKey } from "../../lib/i18n";
import { replaceUrl } from "../../lib/navigate";
import { useConfirm } from "../ConfirmDialog";
import { Badge } from "../ui/Badge";
import { Button, buttonClass } from "../ui/Button";
import { DetailItem, DetailList } from "../ui/DetailList";
import { PanelSection } from "../ui/PanelSection";
import { SheetSync } from "./SheetSync";
import { microAppKey } from "./useMicroAppControl";

const OWNER_LABEL: Record<SheetColumnOwner, MessageKey> = {
  sheet: "microapps.sheets.owner.sheet",
  app: "microapps.sheets.owner.app",
  both: "microapps.sheets.owner.both",
};

const sheetStatusQuery = (assetId: string) =>
  queryOptions({ queryKey: [...microAppKey(assetId), "sheets"], queryFn: () => getSheetStatus(assetId) });

/**
 * The Google Sheets tab: my Google connection, the link of one collection
 * to one sheet tab and the sync on demand (`app.control`). The link, and
 * whether it syncs by itself (`auto_sync`), is set up only by an AI agent
 * through ics-mcp; here it is read-only, apart from removing it
 * (`app.access.manage`).
 */
export function MicroAppSheets({ assetId, base }: { assetId: string; base: string }) {
  const queryClient = useQueryClient();
  const query = sheetStatusQuery(assetId);
  const status = useQuery(query);
  const refresh = () => queryClient.invalidateQueries({ queryKey: query.queryKey });
  // Google sends the browser back here; the same address keeps the tab.
  const connectHref = googleConnectUrl(`${base}?tab=sheets`);

  if (status.error) return <p role="alert" className="text-ui text-danger">{formatApiError(status.error)}</p>;
  if (!status.data) return <p className="text-meta text-text-secondary">{t("common.loading")}</p>;
  const s = status.data;

  return (
    <div className="space-y-4">
      <p className="text-ui text-text-secondary">{t("microapps.sheets.hint")}</p>
      {!s.enabled && (
        <p role="status" className="text-ui text-warning">
          {t("microapps.sheets.disabled")}
        </p>
      )}
      <GoogleConnection status={s} connectHref={connectHref} onChanged={refresh} />
      <PanelSection title={t("microapps.sheets.link")} last={!s.link || !s.rights.run}>
        {s.link ? (
          <LinkSummary
            assetId={assetId}
            link={s.link}
            rowLimit={s.row_limit}
            autoIntervalSeconds={s.auto_interval_seconds}
            autoActiveIntervalSeconds={s.auto_active_interval_seconds ?? 30}
            canRemove={s.rights.configure}
            onRemoved={refresh}
          />
        ) : (
          <NotLinked status={s} connectHref={connectHref} />
        )}
      </PanelSection>
      {s.link && s.rights.run && (
        <PanelSection title={t("microapps.sheets.sync")} last>
          <SheetSync assetId={assetId} status={s} link={s.link} connectHref={connectHref} onChanged={refresh} />
        </PanelSection>
      )}
    </div>
  );
}

/** No link yet: it is created by an AI agent, which reads the spreadsheet
 * with the person's own Google account. */
function NotLinked({ status, connectHref }: { status: SheetStatus; connectHref: string }) {
  const canLink = status.rights.configure && status.enabled;
  return (
    <div className="space-y-2">
      <p className="text-ui text-text-primary">{t("microapps.sheets.notLinked")}</p>
      <p className="text-ui text-text-secondary">
        {t(canLink ? "microapps.sheets.agentHint" : "microapps.sheets.agentHintOthers")}
      </p>
      {canLink && !status.my_google && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-meta text-text-secondary">{t("microapps.sheets.agentGoogle")}</span>
          <a className={buttonClass("secondary", "sm")} href={connectHref}>
            {t("microapps.sheets.google.connect")}
          </a>
        </div>
      )}
    </div>
  );
}

/** What `?google=` says after the consent screen, read once on arrival. */
function connectOutcome(): string | null {
  return new URLSearchParams(window.location.search).get("google");
}

function GoogleConnection({
  status,
  connectHref,
  onChanged,
}: {
  status: SheetStatus;
  connectHref: string;
  onChanged: () => Promise<void>;
}) {
  const confirm = useConfirm();
  const [outcome] = useState(connectOutcome);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The outcome is shown once; a reload or a shared address must not repeat it.
  useEffect(() => {
    if (!outcome) return;
    const params = new URLSearchParams(window.location.search);
    params.delete("google");
    const qs = params.toString();
    replaceUrl(`${window.location.pathname}${qs ? `?${qs}` : ""}`);
  }, [outcome]);

  const disconnect = async () => {
    const ok = await confirm({
      title: t("microapps.sheets.google.disconnectTitle"),
      message: t("microapps.sheets.google.disconnectBody"),
      confirmLabel: t("microapps.sheets.google.disconnect"),
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await disconnectGoogle();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
      await onChanged();
    }
  };

  const email = status.my_google?.email;
  return (
    <PanelSection title={t("microapps.sheets.google.title")}>
      <div className="space-y-2">
        {outcome === "connected" ? (
          <p role="status" className="text-ui text-success">
            {t("microapps.sheets.google.connected")}
          </p>
        ) : (
          outcome && (
            <p role="alert" className="text-ui text-danger">
              {outcome === "declined"
                ? t("microapps.sheets.google.declined")
                : (messageForCode(outcome) ?? t("microapps.sheets.google.connectFailed"))}
            </p>
          )
        )}
        {error && (
          <p role="alert" className="text-ui text-danger">
            {error}
          </p>
        )}
        {email ? (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-ui text-text-primary">{t("microapps.sheets.google.connectedAs", { email })}</span>
            <Button size="sm" variant="ghost" busy={busy} onClick={() => void disconnect()}>
              {t("microapps.sheets.google.disconnect")}
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-ui text-text-secondary">{t("microapps.sheets.google.notConnected")}</span>
            {status.enabled && (
              <a className={buttonClass("secondary", "sm")} href={connectHref}>
                {t("microapps.sheets.google.connect")}
              </a>
            )}
          </div>
        )}
      </div>
    </PanelSection>
  );
}

function LinkSummary({
  assetId,
  link,
  rowLimit,
  autoIntervalSeconds,
  autoActiveIntervalSeconds,
  canRemove,
  onRemoved,
}: {
  assetId: string;
  link: SheetLink;
  rowLimit: number;
  autoIntervalSeconds: number;
  autoActiveIntervalSeconds: number;
  canRemove: boolean;
  onRemoved: () => Promise<void>;
}) {
  const confirm = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const remove = async () => {
    const ok = await confirm({
      title: t("microapps.sheets.removeTitle"),
      message: t("microapps.sheets.removeBody"),
      confirmLabel: t("microapps.sheets.remove"),
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await removeSheetLink(assetId);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
      await onRemoved();
    }
  };

  const keyColumn = link.key_field ? link.columns.find((c) => c.field === link.key_field) : undefined;
  return (
    <div className="space-y-3">
      {error && (
        <p role="alert" className="text-ui text-danger">
          {error}
        </p>
      )}
      <DetailList>
        <DetailItem label={t("microapps.sheets.field.spreadsheet")}>
          <a className="inline-flex items-center gap-1 text-accent hover:underline" href={link.spreadsheet_url} target="_blank" rel="noopener noreferrer">
            {t("microapps.sheets.openSpreadsheet")}
            <ExternalLink size={14} aria-hidden />
          </a>
          {link.paused && (
            <Badge tone="warning" className="ml-2">
              {t("microapps.sheets.paused")}
            </Badge>
          )}
        </DetailItem>
        <DetailItem label={t("microapps.sheets.field.sheetTitle")}>{link.sheet_title}</DetailItem>
        <DetailItem label={t("microapps.sheets.field.collection")}>
          <code className="font-code">{link.collection}</code>
        </DetailItem>
        <DetailItem label={t("microapps.sheets.field.columns")}>
          <ul className="grid gap-0.5">
            {link.columns.map((c) => (
              <li key={c.field}>
                {c.header} <span className="text-text-tertiary">({c.field})</span>
                <span className="text-text-secondary">: {t(OWNER_LABEL[c.owner])}</span>
              </li>
            ))}
          </ul>
        </DetailItem>
        <DetailItem label={t("microapps.sheets.field.matching")}>
          {link.key_field
            ? t("microapps.sheets.matching.key", { header: keyColumn?.header ?? link.key_field, field: link.key_field })
            : t("microapps.sheets.matching.content")}
        </DetailItem>
        <DetailItem label={t("microapps.sheets.field.accountMode")}>
          {t(link.account_mode === "owner_account" ? "microapps.sheets.mode.owner_account" : "microapps.sheets.mode.per_user")}
        </DetailItem>
        <DetailItem label={t("microapps.sheets.field.sync")}>
          <AutoSync link={link} intervalSeconds={autoIntervalSeconds} activeIntervalSeconds={autoActiveIntervalSeconds} />
        </DetailItem>
        <DetailItem label={t("microapps.sheets.field.rowLimit")}>
          {tn("microapps.sheets.rowLimit", rowLimit)}
          <span className="block text-meta text-text-secondary">{t("microapps.sheets.rowLimitHint")}</span>
        </DetailItem>
      </DetailList>
      {canRemove && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="danger" busy={busy} onClick={() => void remove()}>
            {t("microapps.sheets.remove")}
          </Button>
        </div>
      )}
    </div>
  );
}

/** Whether the link syncs by itself and, if it stopped, why: a preview with
 * conflicts or an error waits for a person. */
function AutoSync({
  link,
  intervalSeconds,
  activeIntervalSeconds,
}: {
  link: SheetLink;
  intervalSeconds: number;
  activeIntervalSeconds: number;
}) {
  if (!link.auto_sync) return <span className="text-text-secondary">{t("microapps.sheets.auto.off")}</span>;
  const minutes = Math.max(1, Math.round(intervalSeconds / 60));
  const reason = link.auto_error;
  return (
    <>
      {t("microapps.sheets.auto.on", { seconds: activeIntervalSeconds, minutes })}
      {link.auto_checked_at && (
        <span className="block text-meta text-text-secondary">
          {t("microapps.sheets.auto.checkedAt", { time: formatRelative(link.auto_checked_at) })}
        </span>
      )}
      {reason && (
        <span role="status" className="mt-1 block text-ui text-warning">
          {reason === "conflicts"
            ? t("microapps.sheets.auto.waitingConflicts")
            : t("microapps.sheets.auto.stopped", { reason: messageForCode(reason) ?? reason })}
        </span>
      )}
    </>
  );
}
