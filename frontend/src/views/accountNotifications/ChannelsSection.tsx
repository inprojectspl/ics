import { Bell } from "lucide-react";
import type { EmailMode, NotificationPreferences } from "../../api/notificationTypes";
import { t, type MessageKey } from "../../lib/i18n";
import { CARD, SettingsSection, type PrefsProps } from "./_shared";
import { ChatSettings } from "./ChatSettings";
import { PushDevices } from "./PushDevices";

const EMAIL_MODES: ReadonlyArray<{ value: EmailMode; label: MessageKey; hint?: MessageKey }> = [
  { value: "off", label: "accountNotifications.emailOff" },
  { value: "batched", label: "accountNotifications.emailBatched", hint: "accountNotifications.emailBatchedHint" },
  { value: "daily", label: "accountNotifications.emailDaily", hint: "accountNotifications.emailDailyHint" },
];

function ChannelCard({ title, hint, children }: { title: string; hint?: string; children?: React.ReactNode }) {
  return (
    <div className={CARD}>
      <h3 className="text-ui font-semibold text-text-primary">{title}</h3>
      {hint && <p className="text-meta text-text-tertiary mt-0.5">{hint}</p>}
      {children && <div className="mt-3">{children}</div>}
    </div>
  );
}

interface Props extends PrefsProps {
  onSaved: (prefs: NotificationPreferences) => void;
}

/** Where notifications go: in-app, this browser, e-mail, Google Chat. */
export function ChannelsSection({ prefs, update, onSaved }: Props) {
  return (
    <SettingsSection title={t("accountNotifications.channelsTitle")}>
      <div className="space-y-3">
        <ChannelCard title={t("accountNotifications.channel.app")} hint={t("accountNotifications.appHint")}>
          <p className="inline-flex items-center gap-1.5 text-meta text-text-secondary">
            <Bell size={14} aria-hidden />
            {t("accountNotifications.appAlwaysOn")}
          </p>
        </ChannelCard>

        {prefs.push.available && prefs.push.public_key && (
          <ChannelCard title={t("accountNotifications.channel.push")} hint={t("accountNotifications.pushHint")}>
            <PushDevices publicKey={prefs.push.public_key} />
          </ChannelCard>
        )}

        <ChannelCard
          title={t("accountNotifications.channel.email")}
          hint={
            prefs.email_available
              ? t("accountNotifications.emailHint")
              : t("accountNotifications.emailUnavailable")
          }
        >
          {/* Radio rows, not a segmented control: the hints must be readable
              on a phone (no tooltips on touch) and three labels did not fit 320 px. */}
          <fieldset disabled={!prefs.email_available} className="min-w-0 space-y-1 disabled:opacity-50">
            <legend className="sr-only">{t("accountNotifications.emailModeLabel")}</legend>
            {EMAIL_MODES.map(({ value, label, hint }) => (
              <label
                key={value}
                className="flex items-start gap-3 min-h-11 px-2 py-2 -mx-2 rounded-control cursor-pointer hover:bg-surface-subtle/70"
              >
                <input
                  type="radio"
                  name="email-mode"
                  value={value}
                  checked={prefs.email_mode === value}
                  onChange={() => update({ email_mode: value })}
                  className="mt-0.5 size-4 accent-accent"
                />
                <span className="min-w-0">
                  <span className="block text-ui text-text-primary">{t(label)}</span>
                  {hint && <span className="block text-meta text-text-tertiary">{t(hint)}</span>}
                </span>
              </label>
            ))}
          </fieldset>
        </ChannelCard>

        <ChannelCard title={t("accountNotifications.channel.chat")} hint={t("accountNotifications.chatHint")}>
          <ChatSettings prefs={prefs} update={update} onSaved={onSaved} />
        </ChannelCard>
      </div>
    </SettingsSection>
  );
}
