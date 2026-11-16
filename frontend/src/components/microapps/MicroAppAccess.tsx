import { useState, type FormEvent, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import {
  setMicroAppAccess,
  type MicroAppAccessChange,
  type MicroAppGrantSet,
  type MicroAppPerson,
} from "../../api/microApplications";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { projectListQuery } from "../../lib/queries";
import { PROJECT_ROLE_LABEL } from "../../lib/roles";
import { useConfirm } from "../ConfirmDialog";
import { INPUT_CLASS } from "../Field";
import { AccessList } from "../share/AccessRow";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { DetailItem, DetailList } from "../ui/DetailList";
import { Disclosure } from "../ui/Disclosure";
import { PanelSection } from "../ui/PanelSection";
import { GrantPicker, permissionLabel, type GrantCatalog } from "./GrantPicker";
import { PermissionRow } from "./PermissionRow";
import { microAppAccessQuery } from "./useMicroAppControl";

const NONE: MicroAppGrantSet = { roles: [], permissions: [] };
const rowKey = (id: string, g: MicroAppGrantSet) => `${id}:${g.roles.join(",")}:${g.permissions.join(",")}`;

function accessBadge(p: MicroAppPerson) {
  if (!p.can_open) return <Badge tone="warning">{t("microapps.access.cannotOpen")}</Badge>;
  const role = PROJECT_ROLE_LABEL[p.access as keyof typeof PROJECT_ROLE_LABEL];
  return <Badge tone={p.access === "owner" ? "accent" : "neutral"}>{role ? t(role) : p.access}</Badge>;
}

/**
 * The Access tab (`app.access.manage`): who works in the app in which of its
 * roles (or with single permissions), people and projects, and what each
 * role and permission unlocks. Every save sends the exact set, so repeating
 * it changes nothing.
 */
export function MicroAppAccess({ assetId }: { assetId: string }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const accessQuery = microAppAccessQuery(assetId);
  const access = useQuery(accessQuery);
  const projects = useQuery(projectListQuery).data ?? [];
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = async (change: MicroAppAccessChange, who: string): Promise<boolean> => {
    setError(null);
    setNotice(null);
    try {
      const result = await setMicroAppAccess(assetId, change);
      if (result.still_opens_via) setNotice(t("microapps.access.stillOpensVia", { who, via: result.still_opens_via }));
      return true;
    } catch (err) {
      setError(formatApiError(err));
      return false;
    } finally {
      await queryClient.invalidateQueries({ queryKey: accessQuery.queryKey });
    }
  };

  const remove = async (change: MicroAppAccessChange, who: string) => {
    const ok = await confirm({
      title: t("microapps.access.removeTitle", { who }),
      message: t("microapps.access.removeBody"),
      confirmLabel: t("microapps.access.remove"),
      destructive: true,
    });
    if (ok) await apply(change, who);
  };

  if (access.error) return <p role="alert" className="text-ui text-danger">{formatApiError(access.error)}</p>;
  if (!access.data) return <p className="text-meta text-text-secondary">{t("common.loading")}</p>;
  const { people, permissions, roles } = access.data;
  const catalog: GrantCatalog = { roles, permissions };
  const labelOf = new Map(permissions.map((p) => [p.permission, permissionLabel(p)]));
  const listed = new Set(access.data.projects.map((p) => p.project_id));
  const addable = projects.filter((p) => !listed.has(p.id));

  return (
    <div className="space-y-4">
      <p className="text-ui text-text-secondary">{t("microapps.access.hint")}</p>
      {error && (
        <p role="alert" className="text-ui text-danger">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="text-ui text-warning">
          {notice}
        </p>
      )}
      <PanelSection title={t("microapps.access.people")}>
        <div className="space-y-4">
          <AccessList label={t("microapps.access.people")}>
            {people.map((p) => (
              <PermissionRow
                key={rowKey(p.email, p)}
                name={p.display_name || p.email}
                detail={p.display_name ? <span className="truncate">{p.email}</span> : undefined}
                badge={accessBadge(p)}
                catalog={catalog}
                granted={{ roles: p.roles, permissions: p.permissions }}
                inherited={p.effective_permissions}
                onSave={async (next) => {
                  await apply({ user_email: p.email, ...next, can_open: true }, p.email);
                }}
                onRemove={p.access === "owner" ? undefined : () => remove({ user_email: p.email, ...NONE, can_open: false }, p.email)}
              />
            ))}
          </AccessList>
          <AddForm
            title={t("microapps.access.addPerson")}
            fieldLabel={t("common.email")}
            catalog={catalog}
            onAdd={(email, chosen) => apply({ user_email: email, ...chosen, can_open: true }, email)}
            field={(value, onChange) => (
              <input
                type="email"
                required
                className={INPUT_CLASS}
                placeholder={t("microapps.access.emailPlaceholder")}
                value={value}
                onChange={(e) => onChange(e.target.value)}
              />
            )}
          />
        </div>
      </PanelSection>
      <PanelSection title={t("microapps.access.projects")}>
        <div className="space-y-4">
          <p className="text-meta text-text-secondary">{t("microapps.access.projectsHint")}</p>
          {access.data.projects.length === 0 ? (
            <p className="text-ui text-text-secondary">{t("microapps.access.noProjects")}</p>
          ) : (
            <AccessList label={t("microapps.access.projects")}>
              {access.data.projects.map((p) => (
                <PermissionRow
                  key={rowKey(p.project_id, p)}
                  name={p.name}
                  detail={t(p.members_can_open ? "microapps.access.membersCanOpen" : "microapps.access.membersCannotOpen")}
                  catalog={catalog}
                  granted={{ roles: p.roles, permissions: p.permissions }}
                  onSave={async (next) => {
                    await apply({ project_id: p.project_id, ...next }, p.name);
                  }}
                  onRemove={() => remove({ project_id: p.project_id, ...NONE }, p.name)}
                />
              ))}
            </AccessList>
          )}
          {addable.length > 0 && (
            <AddForm
              title={t("microapps.access.addProject")}
              fieldLabel={t("common.project")}
              catalog={catalog}
              onAdd={(id, chosen) => apply({ project_id: id, ...chosen }, projects.find((p) => p.id === id)?.name ?? id)}
              field={(value, onChange) => (
                <select required className={INPUT_CLASS} value={value} onChange={(e) => onChange(e.target.value)}>
                  <option value="">{t("microapps.access.pickProject")}</option>
                  {addable.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              )}
            />
          )}
        </div>
      </PanelSection>
      {roles.length > 0 && (
        <PanelSection title={t("microapps.access.rolesCatalog")}>
          <DetailList>
            {roles.map((r) => (
              <DetailItem key={r.role} label={r.label}>
                {r.description && <span className="block">{r.description}</span>}
                <span className="text-text-secondary">{r.permissions.map((p) => labelOf.get(p) ?? p).join(", ")}</span>
              </DetailItem>
            ))}
          </DetailList>
        </PanelSection>
      )}
      <PanelSection title={t("microapps.access.catalog")} last>
        {permissions.length === 0 ? (
          <p className="text-ui text-text-secondary">{t("microapps.access.noPermissions")}</p>
        ) : (
          <DetailList>
            {permissions.map((p) => (
              <DetailItem key={p.permission} label={permissionLabel(p)}>
                <code className="mr-1.5 font-code text-text-tertiary">{p.permission}</code>
                {p.description && <span className="block">{p.description}</span>}
                {!p.platform && <span className="block text-text-secondary">{p.allows.join("; ")}</span>}
              </DetailItem>
            ))}
          </DetailList>
        )}
      </PanelSection>
    </div>
  );
}

/** Adds one person or project with the chosen roles and permissions, laid
 * out like the share dialog's "add a person" form. */
function AddForm({
  title,
  fieldLabel,
  catalog,
  onAdd,
  field,
}: {
  title: string;
  fieldLabel: string;
  catalog: GrantCatalog;
  onAdd: (value: string, chosen: MicroAppGrantSet) => Promise<boolean>;
  field: (value: string, onChange: (v: string) => void) => ReactNode;
}) {
  const [value, setValue] = useState("");
  const [chosen, setChosen] = useState<MicroAppGrantSet>(NONE);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const ok = await onAdd(value.trim(), chosen);
    setBusy(false);
    if (ok) {
      setValue("");
      setChosen(NONE);
    }
  };
  return (
    <Disclosure title={title}>
      <form aria-label={title} className="space-y-3 pt-2" onSubmit={(e) => void submit(e)}>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <label className="min-w-0 flex-1">
            <span className="mb-1.5 block text-ui font-medium text-text-primary">{fieldLabel}</span>
            {field(value, setValue)}
          </label>
          <Button type="submit" busy={busy} icon={<Plus size={16} aria-hidden />}>
            {t("common.add")}
          </Button>
        </div>
        <GrantPicker catalog={catalog} value={chosen} onChange={setChosen} label={title} />
      </form>
    </Disclosure>
  );
}
