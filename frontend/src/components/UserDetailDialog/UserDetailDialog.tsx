import { useState } from "react";
import { clsx } from "clsx";
import { AdminUser, api } from "../../api";
import { formatApiError } from "../../lib/apiError";
import { formatBytes, formatTimestamp } from "../../lib/format";
import { t, tn } from "../../lib/i18n";
import { useConfirm } from "../ConfirmDialog";
import { SIGN_IN_LABEL, USER_ROLE_LABEL } from "../../lib/roles";
import { Badge } from "../ui/Badge";
import { DetailItem, DetailList } from "../ui/DetailList";
import { Dialog } from "../ui/Dialog";
import {
  ActionRow,
  DangerZone,
  LimitEditor,
  LockEditor,
  RoleEditor,
  ToggleRow,
} from "./rows";

interface Props {
  user: AdminUser;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
  onDeleted: () => void | Promise<void>;
}

/**
 * Admin per-user panel. Two sections: read-only profile + actions.
 * Actions are grouped by impact (low to high): reset/reinvite, role,
 * limits (storage, bundle), lock, delete. Delete last and confirmation gated.
 */
export function UserDetailDialog({ user, onClose, onChanged, onDeleted }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const confirm = useConfirm();

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await fn();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const usagePct = user.storage_quota_bytes
    ? Math.min(100, (user.asset_bytes / user.storage_quota_bytes) * 100)
    : 0;

  return (
    <Dialog
      eyebrow={t("userDetail.eyebrow")}
      title={user.display_name || user.email}
      onClose={onClose}
      maxWidth="2xl"
    >
      <div className="space-y-6 px-5 py-5 sm:px-6">
        <DetailList>
          <DetailItem label={t("common.email")}>
            <span className="[overflow-wrap:anywhere]">{user.email}</span>
          </DetailItem>
          <DetailItem label={t("common.role")}>{t(USER_ROLE_LABEL[user.role])}</DetailItem>
          <DetailItem label={t("userDetail.signIn")}>
            {t(SIGN_IN_LABEL[user.auth_method])}
          </DetailItem>
          <DetailItem label={t("userDetail.status")}>
            {user.locked ? (
              <Badge tone="warning">
                {user.locked_until
                  ? t("userDetail.lockedUntil", { date: formatTimestamp(user.locked_until) })
                  : t("userDetail.locked")}
              </Badge>
            ) : user.email_verified ? (
              <Badge tone="success">{t("userDetail.active")}</Badge>
            ) : (
              <Badge>{t("userDetail.unverified")}</Badge>
            )}
          </DetailItem>
          <DetailItem label={t("userDetail.created")}>{formatTimestamp(user.created_at)}</DetailItem>
          <DetailItem label={t("userDetail.lastLogin")}>
            {user.last_login_at ? formatTimestamp(user.last_login_at) : t("userDetail.neverSignedIn")}
          </DetailItem>
          <DetailItem label={t("userDetail.assets")}>
            {tn("format.documentCount", user.asset_count)} ·{" "}
            <span className={clsx("tabular-nums", usagePct >= 95 ? "text-danger" : usagePct >= 80 ? "text-warning" : "text-text-secondary")}>
              {formatBytes(user.asset_bytes)} / {formatBytes(user.storage_quota_bytes)} ({Math.round(usagePct)}%)
            </span>
          </DetailItem>
        </DetailList>

        {error && (
          <p role="alert" className="text-ui text-danger">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="text-ui text-success">
            {notice}
          </p>
        )}

        <section>
          <h3 className="text-ui font-semibold text-text-primary">{t("userDetail.actions")}</h3>

          {/* Low risk: sends an email */}
          <ActionRow
            title={t("userDetail.resetTitle")}
            desc={t("userDetail.resetDesc")}
            disabled={user.auth_method !== "password"}
            busy={busy === "reset"}
            onAction={() =>
              run("reset", async () => {
                await api.adminUserPasswordReset(user.id);
                setNotice(t("userDetail.mailSent", { email: user.email }));
              })
            }
            actionLabel={t("userDetail.resetAction")}
          />
          {!user.email_verified && (
            <ActionRow
              title={t("userDetail.reinviteTitle")}
              desc={t("userDetail.reinviteDesc")}
              busy={busy === "reinvite"}
              onAction={() =>
                run("reinvite", async () => {
                  await api.adminUserReinvite(user.id);
                  setNotice(t("userDetail.mailSent", { email: user.email }));
                })
              }
              actionLabel={t("userDetail.reinviteAction")}
            />
          )}

          {/* Editing: role and limits */}
          <RoleEditor user={user} busy={busy === "role"} onChange={(r) =>
            run("role", async () => {
              await api.adminUserPatch(user.id, { role: r });
              await onChanged();
            })
          } />

          <LimitEditor
            title={t("userDetail.quotaTitle")}
            desc={t("userDetail.quotaDesc")}
            unit="GB"
            value={user.storage_quota_bytes}
            busy={busy === "quota"}
            onChange={(b) =>
              run("quota", async () => {
                await api.adminUserPatch(user.id, { storage_quota_bytes: b });
                await onChanged();
              })
            }
          />

          <LimitEditor
            title={t("userDetail.bundleTitle")}
            desc={t("userDetail.bundleDesc")}
            unit="MB"
            value={user.bundle_max_bytes}
            busy={busy === "bundle"}
            onChange={(b) =>
              run("bundle", async () => {
                await api.adminUserPatch(user.id, { bundle_max_bytes: b });
                await onChanged();
              })
            }
          />

          <ToggleRow
            title={t("userDetail.autobypassTitle")}
            desc={t("userDetail.autobypassDesc")}
            checked={user.html_autobypass}
            busy={busy === "autobypass"}
            onChange={(v) =>
              run("autobypass", async () => {
                await api.adminUserPatch(user.id, { html_autobypass: v });
                await onChanged();
              })
            }
          />

          {user.locked ? (
            <ActionRow
              title={t("userDetail.unlockTitle")}
              desc={t("userDetail.unlockDesc")}
              busy={busy === "unlock"}
              onAction={() =>
                run("unlock", async () => {
                  await api.adminUserUnlock(user.id);
                  await onChanged();
                })
              }
              actionLabel={t("userDetail.unlockAction")}
            />
          ) : (
            <LockEditor busy={busy === "lock"} onLock={(mins, reason) =>
              run("lock", async () => {
                await api.adminUserLock(user.id, mins, reason);
                await onChanged();
              })
            } />
          )}

          <ActionRow
            title={t("userDetail.revokeTokensTitle")}
            desc={t("userDetail.revokeTokensDesc")}
            busy={busy === "tokens"}
            onAction={() =>
              run("tokens", async () => {
                const ok = await confirm({
                  title: t("userDetail.revokeTokensConfirm", { email: user.email }),
                  message: t("userDetail.revokeTokensDesc"),
                  confirmLabel: t("userDetail.revokeTokensAction"),
                  destructive: true,
                });
                if (!ok) return;
                const r = await api.adminRevokeUserTokens(user.id);
                setNotice(tn("userDetail.tokensRevoked", r.revoked));
              })
            }
            actionLabel={t("userDetail.revokeTokensAction")}
          />

          {/* High risk: deletion */}
          <DangerZone user={user} busy={busy === "delete"} onDelete={() =>
            run("delete", async () => {
              const ok = await confirm({
                title: t("userDetail.deleteConfirmTitle", { email: user.email }),
                message: tn("userDetail.deleteConfirmMessage", user.asset_count),
                confirmLabel: t("userDetail.deleteAction"),
                destructive: true,
              });
              if (!ok) return;
              const r = await api.adminUserDelete(user.id);
              setNotice(tn("userDetail.deleted", r.cascade_assets));
              await onDeleted();
            })
          } />
        </section>
      </div>
    </Dialog>
  );
}
