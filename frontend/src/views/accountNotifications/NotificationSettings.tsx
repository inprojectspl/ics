import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Me } from "../../api";
import { getPreferences, updatePreferences } from "../../api/notifications";
import type { NotificationPreferences, PreferencesPatch } from "../../api/notificationTypes";
import { CARD, SettingsSection } from "./_shared";
import { AccountPage } from "../../components/AccountPage";
import { PageHeader } from "../../components/ui/PageHeader";
import { Switch } from "../../components/Switch";
import { useErrorToast } from "../../components/Toast";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { applyPatch } from "../../lib/notifications/preferences";
import { useOptimisticUpdate } from "../../lib/notifications/useOptimisticUpdate";
import { qk } from "../../lib/queries";
import { useDocumentTitle } from "../../lib/useDocumentTitle";
import { ChannelsSection } from "./ChannelsSection";
import { EventMatrix } from "./EventMatrix";
import { WatchedItems } from "./WatchedItems";

const PREFS_KEY = qk.notificationPreferences();

/** `/account/notifications`: master switch, channels, what to notify
 * about, own documents and the watched items (ADR-0023, section 8). */
export function NotificationSettings({ me }: { me: Me }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: PREFS_KEY, queryFn: getPreferences });
  const onError = useErrorToast();
  const write = useOptimisticUpdate<NotificationPreferences>(PREFS_KEY, onError);
  useDocumentTitle(t("accountNotifications.title"));

  const prefs = query.data;
  const update = useCallback(
    (patch: PreferencesPatch) => {
      if (prefs) void write(applyPatch(prefs, patch), () => updatePreferences(patch));
    },
    [prefs, write],
  );
  const onSaved = useCallback(
    (next: NotificationPreferences) => qc.setQueryData(PREFS_KEY, next),
    [qc],
  );

  return (
    <AccountPage me={me} tab="notifications">
      <PageHeader title={t("accountNotifications.title")} description={t("accountNotifications.intro")} />
      {query.isPending ? (
        <p className="text-meta text-text-tertiary">{t("common.loading")}</p>
      ) : !prefs ? (
        <p role="alert" className="text-ui text-danger">
          {formatApiError(query.error)}
        </p>
      ) : (
        <>
          <div className={`${CARD} mb-10`}>
            <Switch
              checked={prefs.enabled}
              onChange={(enabled) => update({ enabled })}
              label={t("accountNotifications.master")}
              description={t("accountNotifications.masterHint")}
            />
          </div>
          <div className={prefs.enabled ? undefined : "opacity-60"}>
            <ChannelsSection prefs={prefs} update={update} onSaved={onSaved} />
            <SettingsSection title={t("accountNotifications.eventsTitle")}>
              <EventMatrix prefs={prefs} update={update} />
            </SettingsSection>
            <SettingsSection title={t("accountNotifications.ownTitle")}>
              <div className={CARD}>
                <Switch
                  checked={prefs.watch_own_assets}
                  onChange={(watch_own_assets) => update({ watch_own_assets })}
                  label={t("accountNotifications.own")}
                  description={t("accountNotifications.ownHint")}
                />
              </div>
            </SettingsSection>
          </div>
          <SettingsSection title={t("accountNotifications.watchedTitle")}>
            <WatchedItems />
          </SettingsSection>
        </>
      )}
    </AccountPage>
  );
}
