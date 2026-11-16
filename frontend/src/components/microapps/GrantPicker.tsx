import { clsx } from "clsx";

import type { MicroAppGrantSet, MicroAppPermissionInfo, MicroAppRole } from "../../api/microApplications";
import { t, tn } from "../../lib/i18n";
import { Disclosure } from "../ui/Disclosure";

export interface GrantCatalog {
  roles: readonly MicroAppRole[];
  permissions: readonly MicroAppPermissionInfo[];
}

const sameSet = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((v) => b.includes(v));

export const sameGrants = (a: MicroAppGrantSet, b: MicroAppGrantSet) => sameSet(a.roles, b.roles) && sameSet(a.permissions, b.permissions);

const toggle = (list: readonly string[], value: string, on: boolean) => (on ? [...list, value] : list.filter((x) => x !== value));

const PLATFORM_LABEL = {
  "app.publish": "microapps.platform.publish",
  "app.control": "microapps.platform.control",
} as const;

/** The name people read: the manifest's label, or ICS's own for the
 * platform permissions. */
export function permissionLabel(p: MicroAppPermissionInfo): string {
  const key = PLATFORM_LABEL[p.permission as keyof typeof PLATFORM_LABEL];
  return key ? t(key) : (p.label ?? p.permission);
}

/**
 * What a person, project or link may do in the app: the roles the app
 * defines first, single permissions folded away beside them, and the
 * platform permissions of co-authors and operators kept apart from the
 * app's own.
 */
export function GrantPicker({
  catalog,
  value,
  onChange,
  label,
  inherited = [],
}: {
  catalog: GrantCatalog;
  value: MicroAppGrantSet;
  onChange: (next: MicroAppGrantSet) => void;
  /** Accessible name of the group: whose access this is. */
  label: string;
  /** Permissions held another way (a project): shown, not editable here. */
  inherited?: readonly string[];
}) {
  const { roles, permissions } = catalog;
  if (roles.length === 0) {
    return <p className="text-meta text-text-tertiary">{t("microapps.access.noPermissions")}</p>;
  }
  // Which chosen role gives each permission, so a single grant is not asked for twice.
  const byRole = new Map<string, string>();
  for (const r of roles) if (value.roles.includes(r.role)) for (const p of r.permissions) if (!byRole.has(p)) byRole.set(p, r.label);

  const check = (p: MicroAppPermissionInfo) => {
    const role = byRole.get(p.permission);
    const via = !role && inherited.includes(p.permission) && !value.permissions.includes(p.permission);
    const hint = role ? t("microapps.access.fromRole", { role }) : via ? t("microapps.access.viaProject") : undefined;
    return (
      <label key={p.permission} className="flex items-baseline gap-2 text-meta" title={p.description ?? hint}>
        <input
          type="checkbox"
          className="size-4 shrink-0 translate-y-0.5 accent-accent"
          checked={Boolean(role) || value.permissions.includes(p.permission)}
          disabled={Boolean(role)}
          onChange={(e) => onChange({ ...value, permissions: toggle(value.permissions, p.permission, e.target.checked) })}
        />
        <span className={via || role ? "text-text-tertiary" : undefined}>
          {permissionLabel(p)}
          <code className="ml-1.5 font-code text-text-tertiary">{p.permission}</code>
          {hint && <span className="ml-1.5 text-text-tertiary">({hint})</span>}
        </span>
      </label>
    );
  };
  const app = permissions.filter((p) => !p.platform);
  const platform = permissions.filter((p) => p.platform);

  return (
    <div className="mt-1 w-full space-y-2">
      <fieldset aria-label={t("microapps.access.rolesOf", { name: label })} className="flex flex-wrap gap-2">
        {roles.map((r) => {
          const on = value.roles.includes(r.role);
          return (
            <label
              key={r.role}
              title={r.description ?? undefined}
              className={clsx(
                "inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border px-3 text-ui transition-colors duration-150",
                on
                  ? "border-accent bg-accent-soft font-medium text-text-primary"
                  : "border-border bg-surface text-text-secondary hover:bg-surface-hover hover:text-text-primary",
              )}
            >
              <input
                type="checkbox"
                className="size-4 accent-accent"
                checked={on}
                onChange={(e) => onChange({ ...value, roles: toggle(value.roles, r.role, e.target.checked) })}
              />
              <span>{r.label}</span>
            </label>
          );
        })}
      </fieldset>
      <Disclosure
        title={<span className="text-meta font-normal text-text-secondary">{t("microapps.access.singlePermissions")}</span>}
        aside={
          value.permissions.length > 0 ? (
            <span className="text-meta text-text-secondary">{tn("microapps.access.singleCount", value.permissions.length)}</span>
          ) : undefined
        }
        defaultOpen={value.permissions.length > 0}
      >
        <div className="space-y-3 pt-1 pl-6">
          <fieldset aria-label={t("microapps.access.singlePermissionsOf", { name: label })} className="flex w-full flex-col gap-1">
            {app.map(check)}
          </fieldset>
          {platform.length > 0 && (
            <fieldset aria-label={t("microapps.access.platformOf", { name: label })} className="flex w-full flex-col gap-1">
              <legend className="mb-1 text-meta font-medium text-text-secondary">{t("microapps.access.platform")}</legend>
              {platform.map(check)}
            </fieldset>
          )}
        </div>
      </Disclosure>
    </div>
  );
}
