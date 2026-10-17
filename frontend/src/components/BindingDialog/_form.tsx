import { clsx } from "clsx";
import { ReactNode } from "react";
import type {
  NotificationProviderId,
  NotificationProviderInfo,
} from "../../api";
import { t } from "../../lib/i18n";

export const textInputClasses = clsx(
  "block w-full h-11 px-3 rounded-control",
  "bg-surface border border-border text-text-primary",
  "text-ui focus:border-accent focus:outline-none",
);

export const compactInputClasses = clsx(
  "h-8 px-2 rounded-xs",
  "bg-surface border border-border text-text-primary",
  "font-code text-meta focus:border-accent focus:outline-none",
);

export function FormLabel({ text, children }: { text: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-ui font-medium text-text-primary">
        {text}
      </span>
      {children}
    </label>
  );
}

export function ProviderSelect({
  providers,
  value,
  onChange,
  compact = false,
}: {
  providers: NotificationProviderInfo[] | null;
  value: NotificationProviderId | "";
  onChange: (id: NotificationProviderId | "") => void;
  compact?: boolean;
}) {
  const klass = compact ? compactInputClasses : textInputClasses;
  return (
    <select
      value={value}
      onChange={(e) => onChange((e.target.value || "") as NotificationProviderId | "")}
      disabled={providers === null}
      className={clsx(klass, "appearance-none")}
    >
      <option value="">{t("bindingDialog.noNotification")}</option>
      {providers?.map((p) => (
        <option key={p.id} value={p.id}>
          {p.display_name}
        </option>
      ))}
    </select>
  );
}
