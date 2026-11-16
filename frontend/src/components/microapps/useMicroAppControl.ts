import { useState } from "react";
import { queryOptions, useQueryClient } from "@tanstack/react-query";

import { controlMicroApp, getMicroAppAccess, type MicroApp, type MicroAppAction } from "../../api/microApplications";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { useConfirm } from "../ConfirmDialog";

export const microAppKey = (assetId: string) => ["microapps", assetId] as const;

/** Who has which roles, plus the app's role and permission catalog; the
 * Access tab and the share dialog read the same cached answer. */
export const microAppAccessQuery = (assetId: string) =>
  queryOptions({ queryKey: [...microAppKey(assetId), "access"], queryFn: () => getMicroAppAccess(assetId) });

/** Enable, suspend, sleep and restart of one app. Suspending refuses new
 * requests at once, so it asks first; the rest are harmless to repeat. */
export function useMicroAppControl(app: MicroApp) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [busy, setBusy] = useState<MicroAppAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: MicroAppAction) => {
    if (action === "suspend") {
      const ok = await confirm({
        title: t("microapps.suspendTitle", { name: app.title ?? app.slug }),
        message: t("microapps.suspendBody"),
        confirmLabel: t("microapps.action.suspend"),
        destructive: true,
      });
      if (!ok) return;
    }
    setBusy(action);
    setError(null);
    try {
      await controlMicroApp(app.asset_id, action, app.generation);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(null);
      await queryClient.invalidateQueries({ queryKey: microAppKey(app.asset_id), exact: true });
    }
  };

  return { run, busy, error };
}
