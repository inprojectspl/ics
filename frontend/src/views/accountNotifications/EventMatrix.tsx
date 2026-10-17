import { clsx } from "clsx";
import { Check } from "lucide-react";
import type { EventKind, OptionalChannel } from "../../api/notificationTypes";
import { t } from "../../lib/i18n";
import {
  CHANNELS,
  CHANNEL_LABEL,
  EVENT_KINDS,
  EVENT_LABEL,
  channelBlocker,
  toggleChannel,
} from "../../lib/notifications/preferences";
import { CARD, type PrefsProps } from "./_shared";

const COL_HEAD = "px-3 py-2.5 text-center text-meta font-normal text-text-tertiary";

/** In-app delivery has no setting (ADR-0023): a fixed, ticked column. */
function AlwaysOn() {
  return (
    <span title={t("accountNotifications.appAlwaysOn")} className="inline-flex text-text-tertiary">
      <Check size={16} aria-hidden />
      <span className="sr-only">{t("accountNotifications.appAlwaysOn")}</span>
    </span>
  );
}

/**
 * What to notify about: event kinds by channel. A table from `sm` up; on a
 * phone one card per event with a chip per channel. A channel that cannot
 * deliver (not configured, e-mail off) stays visible but disabled, with the
 * reason in its tooltip.
 */
export function EventMatrix({ prefs, update }: PrefsProps) {
  const toggle = (kind: EventKind, channel: OptionalChannel) =>
    update({ events: { [kind]: toggleChannel(prefs.events[kind], channel) } });
  const blocker = (channel: OptionalChannel) => {
    const key = channelBlocker(prefs, channel);
    return key ? t(key) : undefined;
  };
  const appLabel = t("accountNotifications.channel.app");

  return (
    <>
      <div className={clsx(CARD, "hidden sm:block p-0 overflow-x-auto")}>
        <table className="w-full text-ui">
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="px-4 py-2.5 text-left text-meta font-normal text-text-tertiary">
                {t("accountNotifications.eventColumn")}
              </th>
              <th scope="col" className={COL_HEAD}>
                {appLabel}
              </th>
              {CHANNELS.map((channel) => (
                <th key={channel} scope="col" title={blocker(channel)} className={COL_HEAD}>
                  {t(CHANNEL_LABEL[channel])}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {EVENT_KINDS.map((kind) => (
              <tr key={kind} className="border-b border-border last:border-0">
                <th scope="row" className="px-4 py-2.5 text-left font-normal text-text-primary">
                  {t(EVENT_LABEL[kind])}
                </th>
                <td className="px-3 py-2.5 text-center">
                  <AlwaysOn />
                </td>
                {CHANNELS.map((channel) => (
                  <td key={channel} className="px-3 py-2.5 text-center">
                    <input
                      type="checkbox"
                      checked={prefs.events[kind].includes(channel)}
                      disabled={channelBlocker(prefs, channel) !== null}
                      title={blocker(channel)}
                      onChange={() => toggle(kind, channel)}
                      aria-label={t("accountNotifications.cellLabel", {
                        event: t(EVENT_LABEL[kind]),
                        channel: t(CHANNEL_LABEL[channel]),
                      })}
                      className="size-4 accent-accent disabled:opacity-40"
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="sm:hidden space-y-2">
        {EVENT_KINDS.map((kind) => (
          <li key={kind} className={CARD}>
            <p className="text-ui font-medium text-text-primary mb-2">{t(EVENT_LABEL[kind])}</p>
            <div className="flex flex-wrap gap-2">
              <span
                title={t("accountNotifications.appAlwaysOn")}
                className="inline-flex items-center gap-1 min-h-9 px-3 rounded-full border border-border bg-surface-subtle text-ui text-text-secondary"
              >
                <Check size={14} aria-hidden />
                {appLabel}
              </span>
              {CHANNELS.map((channel) => {
                const on = prefs.events[kind].includes(channel);
                return (
                  <button
                    key={channel}
                    type="button"
                    aria-pressed={on}
                    disabled={channelBlocker(prefs, channel) !== null}
                    title={blocker(channel)}
                    onClick={() => toggle(kind, channel)}
                    className={clsx(
                      "inline-flex items-center gap-1 min-h-9 px-3 rounded-full border text-ui transition-colors",
                      "disabled:opacity-40",
                      on ? "border-accent bg-accent/10 text-text-primary" : "border-border text-text-tertiary",
                    )}
                  >
                    {on && <Check size={14} aria-hidden className="text-accent" />}
                    {t(CHANNEL_LABEL[channel])}
                  </button>
                );
              })}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
