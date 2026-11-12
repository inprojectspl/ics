import { t } from "../../lib/i18n";

/** One checkbox per permission of the app; `onChange` gets the new set. */
export function PermissionChecks({
  permissions,
  chosen,
  onChange,
  label,
  inherited = [],
}: {
  permissions: readonly string[];
  chosen: readonly string[];
  onChange: (next: string[]) => void;
  /** Accessible name of the group: whose permissions these are. */
  label: string;
  /** Held through a project: shown, not editable here. */
  inherited?: readonly string[];
}) {
  if (permissions.length === 0) return <p className="text-meta text-text-tertiary">{t("microapps.access.noPermissions")}</p>;
  return (
    <fieldset aria-label={label} className="mt-1 flex w-full flex-wrap gap-x-4 gap-y-1">
      {permissions.map((p) => {
        const via = inherited.includes(p) && !chosen.includes(p);
        return (
          <label key={p} className="flex items-center gap-1.5 text-meta" title={via ? t("microapps.access.viaProject") : undefined}>
            <input
              type="checkbox"
              className="size-4 accent-accent"
              checked={chosen.includes(p)}
              onChange={(e) => onChange(e.target.checked ? [...chosen, p] : chosen.filter((x) => x !== p))}
            />
            <code className={via ? "font-code text-text-tertiary" : "font-code"}>{p}</code>
          </label>
        );
      })}
    </fieldset>
  );
}
