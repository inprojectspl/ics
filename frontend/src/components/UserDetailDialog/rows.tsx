/**
 * Setting rows of the user panel. Each keeps its own form state but
 * delegates the mutation upward: the parent owns busy/error and refreshing
 * data after the PATCH.
 */
import { useState, type ReactNode } from "react";
import type { AdminUser, UserRole } from "../../api";
import { t, tn, type MessageKey } from "../../lib/i18n";
import { USER_ROLE_LABEL } from "../../lib/roles";
import { INPUT_CLASS, inputClass } from "../Field";
import { Switch } from "../Switch";
import { Button } from "../ui/Button";

/** Title and explanation on the left, the control on the right; stacked on
 * phones. `below` spans the row under both (a reason field). */
function SettingRow({
  title,
  desc,
  children,
  below,
}: {
  title: string;
  desc: ReactNode;
  children: ReactNode;
  below?: ReactNode;
}) {
  return (
    <div className="border-t border-border py-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-6">
        <div className="min-w-0 flex-1">
          <p className="text-ui font-medium text-text-primary">{title}</p>
          <p className="mt-0.5 text-meta text-text-secondary">{desc}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">{children}</div>
      </div>
      {below && <div className="mt-3">{below}</div>}
    </div>
  );
}

const COMPACT = inputClass({ size: "sm", full: false });

export function ActionRow({
  title,
  desc,
  actionLabel,
  onAction,
  busy,
  disabled,
}: {
  title: string;
  desc: string;
  actionLabel: string;
  onAction: () => void;
  busy: boolean;
  disabled?: boolean;
}) {
  return (
    <SettingRow title={title} desc={desc}>
      <Button variant="secondary" size="sm" onClick={onAction} busy={busy} disabled={disabled}>
        {actionLabel}
      </Button>
    </SettingRow>
  );
}

const ROLES: readonly UserRole[] = ["user", "external", "admin"];
const ROLE_DESC: Record<UserRole, MessageKey> = {
  user: "userDetail.roleDescUser",
  external: "userDetail.roleDescExternal",
  admin: "userDetail.roleDescAdmin",
};

export function RoleEditor({
  user,
  busy,
  onChange,
}: {
  user: AdminUser;
  busy: boolean;
  onChange: (role: UserRole) => void;
}) {
  const [picked, setPicked] = useState<UserRole>(user.role);
  return (
    <SettingRow title={t("common.role")} desc={t(ROLE_DESC[picked])}>
      <select
        aria-label={t("common.role")}
        value={picked}
        onChange={(e) => setPicked(e.target.value as UserRole)}
        disabled={busy}
        className={`${COMPACT} w-48`}
      >
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {t(USER_ROLE_LABEL[r])}
          </option>
        ))}
      </select>
      <Button variant="secondary" size="sm" onClick={() => onChange(picked)} busy={busy} disabled={picked === user.role}>
        {t("common.apply")}
      </Button>
    </SettingRow>
  );
}

/**
 * Row with a toggle. The parent holds the state (the API value), so after
 * a failed PATCH the toggle reverts to the server truth instead of staying
 * in a position the database never confirmed.
 */
export function ToggleRow({
  title,
  desc,
  checked,
  busy,
  onChange,
}: {
  title: string;
  desc: string;
  checked: boolean;
  busy: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="border-t border-border py-4">
      <Switch label={title} description={desc} checked={checked} disabled={busy} onChange={onChange} />
    </div>
  );
}

const UNIT_BYTES = { GB: 1024 ** 3, MB: 1024 ** 2 } as const;

/**
 * A single "label + number + unit + apply" row. The value is kept in display
 * units (GB/MB) and converted to bytes only on save; otherwise typing "1.5"
 * would get lost to rounding in the field.
 */
export function LimitEditor({
  title,
  desc,
  unit,
  value,
  busy,
  onChange,
}: {
  title: string;
  desc: string;
  unit: keyof typeof UNIT_BYTES;
  value: number;
  busy: boolean;
  onChange: (bytes: number) => void;
}) {
  const unitBytes = UNIT_BYTES[unit];
  const [text, setText] = useState(() => (value / unitBytes).toFixed(1));
  const parsed = Number(text);
  const bytes = isFinite(parsed) ? Math.round(parsed * unitBytes) : value;
  const changed = bytes !== value;

  return (
    <SettingRow title={title} desc={desc}>
      <label className="flex items-center gap-2">
        <span className="sr-only">{title}</span>
        <input
          type="number"
          min={0}
          step="0.1"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={busy}
          className={`${COMPACT} w-24 text-right tabular-nums`}
        />
        <span className="text-meta text-text-secondary">{unit}</span>
      </label>
      <Button variant="secondary" size="sm" onClick={() => onChange(bytes)} busy={busy} disabled={!changed}>
        {t("common.apply")}
      </Button>
    </SettingRow>
  );
}

export function LockEditor({
  busy,
  onLock,
}: {
  busy: boolean;
  onLock: (minutes: number, reason: string) => void;
}) {
  const [duration, setDuration] = useState<15 | 60 | 1440>(15);
  const [reason, setReason] = useState("");
  return (
    <SettingRow
      title={t("userDetail.lockTitle")}
      desc={t("userDetail.lockDesc")}
      below={
        <input
          type="text"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={t("userDetail.lockReason")}
          aria-label={t("userDetail.lockReason")}
          disabled={busy}
          className={INPUT_CLASS}
        />
      }
    >
      <select
        aria-label={t("userDetail.lockTitle")}
        value={duration}
        onChange={(e) => setDuration(Number(e.target.value) as 15 | 60 | 1440)}
        disabled={busy}
        className={`${COMPACT} w-36`}
      >
        <option value={15}>{t("userDetail.lock15m")}</option>
        <option value={60}>{t("userDetail.lock1h")}</option>
        <option value={1440}>{t("userDetail.lock24h")}</option>
      </select>
      <Button variant="secondary" size="sm" onClick={() => onLock(duration, reason)} busy={busy}>
        {t("userDetail.lockAction")}
      </Button>
    </SettingRow>
  );
}

export function DangerZone({
  user,
  busy,
  onDelete,
}: {
  user: AdminUser;
  busy: boolean;
  onDelete: () => void;
}) {
  return (
    <section className="mt-2 rounded-card border border-danger/30 px-4">
      <h3 className="pt-3 text-meta font-semibold text-danger">{t("userDetail.dangerZone")}</h3>
      <div className="flex flex-col gap-3 py-3 sm:flex-row sm:items-start sm:gap-6">
        <div className="min-w-0 flex-1">
          <p className="text-ui font-medium text-text-primary">{t("userDetail.deleteAction")}</p>
          <p className="mt-0.5 text-meta text-text-secondary">{tn("userDetail.deleteDesc", user.asset_count)}</p>
        </div>
        <Button variant="danger" size="sm" onClick={onDelete} busy={busy} className="shrink-0 self-start">
          {t("userDetail.deleteAction")}
        </Button>
      </div>
    </section>
  );
}
