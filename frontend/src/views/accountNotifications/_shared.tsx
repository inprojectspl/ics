import type { ReactNode } from "react";
import type { NotificationPreferences, PreferencesPatch } from "../../api/notificationTypes";

export const CARD = "rounded-card border border-border bg-surface p-4";

export function SettingsSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="mb-10">
      <h2 className="text-meta text-text-secondary mb-3 font-medium">{title}</h2>
      {children}
    </section>
  );
}

export interface PrefsProps {
  prefs: NotificationPreferences;
  update: (patch: PreferencesPatch) => void;
}
