import { useState, type ReactNode } from "react";

import type { MicroAppGrantSet } from "../../api/microApplications";
import { t } from "../../lib/i18n";
import { AccessRow } from "../share/AccessRow";
import { Button } from "../ui/Button";
import { GrantPicker, sameGrants, type GrantCatalog } from "./GrantPicker";

/** One person or project in an access list, with its roles and permissions
 * in the app edited in place and saved as one exact set. */
export function PermissionRow({
  name,
  detail,
  badge,
  catalog,
  granted,
  inherited,
  onSave,
  onRemove,
}: {
  name: string;
  detail?: ReactNode;
  badge?: ReactNode;
  catalog: GrantCatalog;
  granted: MicroAppGrantSet;
  inherited?: readonly string[];
  onSave: (next: MicroAppGrantSet) => Promise<void>;
  /** Absent for the owner, who cannot be removed. */
  onRemove?: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<MicroAppGrantSet>(granted);
  const [busy, setBusy] = useState<"save" | "remove" | null>(null);
  const act = async (kind: "save" | "remove", fn: () => Promise<void>) => {
    setBusy(kind);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };
  return (
    <AccessRow
      title={name}
      detail={
        <>
          {detail}
          <GrantPicker catalog={catalog} value={draft} onChange={setDraft} inherited={inherited} label={name} />
        </>
      }
      badge={badge}
      actions={
        <>
          <Button size="sm" variant="secondary" disabled={sameGrants(draft, granted)} busy={busy === "save"} onClick={() => void act("save", () => onSave(draft))}>
            {t("common.save")}
          </Button>
          {onRemove && (
            <Button size="sm" variant="ghost" busy={busy === "remove"} onClick={() => void act("remove", onRemove)}>
              {t("microapps.access.remove")}
            </Button>
          )}
        </>
      }
    />
  );
}
