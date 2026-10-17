import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Info, Smartphone } from "lucide-react";
import { deletePushDevice, listPushDevices } from "../../api/notifications";
import type { PushDevice } from "../../api/notificationTypes";
import { Button } from "../../components/ui/Button";
import { useToast } from "../../components/Toast";
import { formatApiError } from "../../lib/apiError";
import { formatShortDate } from "../../lib/format";
import { t, type MessageKey } from "../../lib/i18n";
import {
  disablePushHere,
  enablePush,
  hasPushHere,
  isBrave,
  pushSupport,
  thisDeviceId,
  type PushSupport,
} from "../../lib/notifications/push";
import { qk } from "../../lib/queries";

const SUPPORT_HINT: Record<PushSupport, MessageKey | null> = {
  supported: null,
  unsupported: "accountNotifications.pushUnsupported",
  "ios-install": "accountNotifications.pushIos",
  denied: "accountNotifications.pushDenied",
};

function Hint({ text }: { text: string }) {
  return (
    <p className="flex items-start gap-2 text-meta text-text-tertiary">
      <Info size={14} aria-hidden className="mt-0.5 shrink-0" />
      {text}
    </p>
  );
}

/**
 * Browser push per device: enabling asks for the permission only on the
 * click, then registers the service worker and the subscription.
 */
export function PushDevices({ publicKey }: { publicKey: string }) {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const support = pushSupport();
  const devices = useQuery({ queryKey: qk.pushDevices(), queryFn: listPushDevices });
  const here = useQuery({ queryKey: qk.pushHere(), queryFn: hasPushHere });
  const hint = SUPPORT_HINT[support];

  const refresh = () => qc.invalidateQueries({ queryKey: qk.pushDevices() });

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } catch (err) {
      toast(formatApiError(err), "error");
    } finally {
      setBusy(false);
      void refresh();
    }
  };

  const onEnable = () =>
    run(async () => {
      if ((await enablePush(publicKey)) === "denied") toast(t("accountNotifications.pushDenied"), "error");
    });
  const onDisable = () => run(disablePushHere);
  const onRemove = (device: PushDevice) =>
    run(async () => {
      if (device.id === thisDeviceId()) {
        await disablePushHere();
        return;
      }
      await deletePushDevice(device.id);
    });

  const items = devices.data?.items ?? [];
  const current = thisDeviceId();

  return (
    <div className="space-y-3">
      {hint && <Hint text={t(hint)} />}
      {isBrave() && <Hint text={t("accountNotifications.pushBrave")} />}
      {support === "supported" &&
        (here.data ? (
          <Button variant="secondary" size="sm" onClick={() => void onDisable()} disabled={busy}>
            {t("accountNotifications.pushDisableHere")}
          </Button>
        ) : (
          <Button size="sm" onClick={() => void onEnable()} disabled={busy || here.isPending}>
            <BellRing size={14} aria-hidden />
            {t("accountNotifications.pushEnable")}
          </Button>
        ))}
      {items.length > 0 && (
        <ul aria-label={t("accountNotifications.pushDevices")} className="divide-y divide-border">
          {items.map((device) => (
            <li key={device.id} className="flex items-center gap-3 py-2.5">
              <Smartphone size={16} aria-hidden className="shrink-0 text-text-tertiary" />
              <div className="min-w-0 flex-1">
                <p className="text-ui text-text-primary truncate">
                  {device.label}
                  {device.id === current && (
                    <span className="ml-2 text-meta text-accent">{t("accountNotifications.pushThisDevice")}</span>
                  )}
                </p>
                <p className="text-meta text-text-tertiary">
                  {t("accountNotifications.pushAdded", { date: formatShortDate(device.created_at) })}
                  {device.last_success_at &&
                    ` · ${t("accountNotifications.pushLastSent", { date: formatShortDate(device.last_success_at) })}`}
                </p>
              </div>
              <Button
                variant="danger"
                size="sm"
                onClick={() => void onRemove(device)}
                disabled={busy}
                aria-label={t("accountNotifications.pushRemove", { label: device.label })}
              >
                {t("common.delete")}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
