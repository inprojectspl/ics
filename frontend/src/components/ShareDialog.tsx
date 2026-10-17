import { FormEvent, useCallback, useEffect, useState } from "react";
import { clsx } from "clsx";
import { Check, Copy, Link2Off, UserPlus } from "lucide-react";
import { api, AssetShareRow, AssetSummary, ShareLink } from "../api";
import { formatApiError, statusCode } from "../lib/apiError";
import { formatShortDate } from "../lib/format";
import { t, tn } from "../lib/i18n";
import { useClipboard } from "../lib/useClipboard";
import { useConfirm } from "./ConfirmDialog";
import { INPUT_CLASS } from "./Field";
import { ProjectSharesSection } from "./ProjectSharesSection";
import { AccessList, AccessRow } from "./share/AccessRow";
import { NewLinkForm, type NewLink } from "./share/NewLinkForm";
import { MODE_INFO } from "./share/shareModes";
import { useToast } from "./Toast";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { Disclosure } from "./ui/Disclosure";
import { IconButton } from "./ui/IconButton";
import { canManage } from "../lib/assetRoles";

interface Props {
  asset: AssetSummary;
  onClose: () => void;
}

type ShareTab = "links" | "people" | "projects";

export function ShareDialog({ asset, onClose }: Props) {
  const [shares, setShares] = useState<ShareLink[] | null>(null);
  const [userShares, setUserShares] = useState<AssetShareRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [tab, setTab] = useState<ShareTab>("links");

  const [userShareEmail, setUserShareEmail] = useState("");
  const [userShareRole, setUserShareRole] = useState<"editor" | "viewer">("viewer");
  const [userShareBusy, setUserShareBusy] = useState(false);

  const { copy, copiedKey } = useClipboard();
  const confirm = useConfirm();
  const { toast } = useToast();

  // Fetch each list independently - if the caller is a project editor
  // (viewing a file but not allowed to share it), only one of these
  // 403s and we still want to show the other panel correctly.
  const refresh = useCallback(
    () =>
      Promise.allSettled([api.listShares(asset.id), api.listAssetShares(asset.slug)]).then(
        ([linksRes, usersRes]) => {
          if (linksRes.status === "fulfilled") setShares(linksRes.value);
          if (usersRes.status === "fulfilled") setUserShares(usersRes.value);
          const firstErr =
            linksRes.status === "rejected"
              ? linksRes.reason
              : usersRes.status === "rejected"
                ? usersRes.reason
                : null;
          if (firstErr && [linksRes, usersRes].every((r) => r.status === "rejected")) {
            const code = statusCode(firstErr);
            setError(
              code === 403 || code === 404
                ? t("shareDialog.ownerOnly")
                : formatApiError(firstErr),
            );
          }
        },
      ),
    [asset.id, asset.slug],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onAddUserShare = async (e: FormEvent) => {
    e.preventDefault();
    if (!userShareEmail.trim()) return;
    setUserShareBusy(true);
    try {
      const row = await api.createAssetShare(
        asset.slug, userShareEmail.trim(), userShareRole,
      );
      setUserShareEmail("");
      toast(
        row.new_account
          ? t("shareDialog.invitedNew", { email: row.email })
          : t("shareDialog.shared", { email: row.email }),
        "success",
      );
      await refresh();
    } catch (err) {
      toast(formatApiError(err, t("shareDialog.shareFailed")), "error");
    } finally {
      setUserShareBusy(false);
    }
  };

  const onRevokeUserShare = async (row: AssetShareRow) => {
    const ok = await confirm({
      title: t("shareDialog.revokeUserTitle", { email: row.email }),
      message: t("shareDialog.revokeUserMessage"),
      confirmLabel: t("shareDialog.revokeUserConfirm"),
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.deleteAssetShare(asset.slug, row.user_id);
      await refresh();
    } catch (e) {
      toast(formatApiError(e), "error");
    }
  };

  const onCreate = async (link: NewLink): Promise<boolean> => {
    setError(null);
    setBusy(true);
    try {
      await api.createShare(asset.id, link);
      await refresh();
      return true;
    } catch (e) {
      setError(formatApiError(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const onRevoke = async (id: string) => {
    const ok = await confirm({
      title: t("shareDialog.revokeLinkTitle"),
      message: t("shareDialog.revokeLinkMessage"),
      confirmLabel: t("shareDialog.revokeLinkConfirm"),
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.revokeShare(id);
      await refresh();
    } catch (e) {
      setError(formatApiError(e));
    }
  };

  // If both lists 403/404'd, the caller has no rights here: one note
  // instead of forms that would all fail on submit.
  const fullyBlocked = error !== null && shares === null && userShares === null;
  const title = asset.title || asset.slug;
  if (fullyBlocked) {
    return (
      <Dialog eyebrow={t("common.share")} title={title} onClose={onClose}>
        <p className="px-6 py-8 text-center text-ui text-text-secondary">{error}</p>
      </Dialog>
    );
  }

  const live = shares?.filter((s) => !s.revoked_at) ?? [];
  const tabs: Array<{ key: ShareTab; label: string }> = [
    { key: "links", label: `${t("shareDialog.tabLinks")}${live.length ? ` (${live.length})` : ""}` },
    { key: "people", label: `${t("shareDialog.tabPeople")}${userShares?.length ? ` (${userShares.length})` : ""}` },
    ...(canManage(asset) ? [{ key: "projects" as const, label: t("shareDialog.tabProjects") }] : []),
  ];

  return (
    <Dialog eyebrow={t("common.share")} title={title} onClose={onClose} maxWidth="2xl">
      <div role="tablist" aria-label={t("common.share")} className="sticky top-0 z-10 flex gap-1 border-b border-border bg-surface px-5 sm:px-6">
        {tabs.map((x) => (
          <button
            key={x.key}
            type="button"
            role="tab"
            aria-selected={x.key === tab}
            onClick={() => setTab(x.key)}
            className={clsx(
              "relative h-10 px-2.5 text-ui transition-colors duration-150",
              x.key === tab
                ? "font-medium text-text-primary after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:rounded-full after:bg-accent"
                : "text-text-secondary hover:text-text-primary",
            )}
          >
            {x.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" className="space-y-6 px-5 py-5 sm:px-6">
        {tab === "links" && (
          <>
            <section aria-label={t("shareDialog.activeLinks")}>
              {shares === null ? (
                <p className="text-meta text-text-secondary">{t("common.loading")}</p>
              ) : shares.length === 0 ? (
                <p className="text-ui text-text-secondary">{t("shareDialog.noLinks")}</p>
              ) : (
                <AccessList label={t("shareDialog.activeLinks")}>
                  {shares.map((s) => (
                    <LinkRow key={s.id} share={s} copied={copiedKey === s.url} onCopy={() => copy(s.url, s.url)} onRevoke={() => void onRevoke(s.id)} />
                  ))}
                </AccessList>
              )}
            </section>
            {/* Mounted once the list is known: with no link yet the form starts open. */}
            {shares !== null && (
              <Disclosure title={t("shareDialog.newLink")} defaultOpen={live.length === 0}>
                <NewLinkForm busy={busy} error={error} onCreate={onCreate} onInvalid={setError} />
              </Disclosure>
            )}
          </>
        )}

        {tab === "people" && (
          <section className="space-y-4">
            <p className="text-ui text-text-secondary">{t("shareDialog.byEmailIntro")}</p>
            <form onSubmit={onAddUserShare} className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <label className="min-w-0 flex-1">
                <span className="mb-1.5 block text-ui font-medium text-text-primary">{t("shareDialog.emailLabel")}</span>
                <input
                  type="email"
                  required
                  value={userShareEmail}
                  onChange={(e) => setUserShareEmail(e.target.value)}
                  placeholder={t("shareDialog.emailPlaceholder")}
                  className={INPUT_CLASS}
                />
              </label>
              <label className="sm:w-40">
                <span className="mb-1.5 block text-ui font-medium text-text-primary">{t("common.role")}</span>
                <select value={userShareRole} onChange={(e) => setUserShareRole(e.target.value as "editor" | "viewer")} className={INPUT_CLASS}>
                  <option value="viewer">{t("shareDialog.roleViewer")}</option>
                  <option value="editor">{t("shareDialog.roleEditor")}</option>
                </select>
              </label>
              <Button type="submit" busy={userShareBusy} icon={<UserPlus size={16} aria-hidden />}>
                {t("common.add")}
              </Button>
            </form>
            {userShares === null ? (
              <p className="text-meta text-text-secondary">{t("common.loading")}</p>
            ) : userShares.length === 0 ? (
              <p className="text-ui text-text-secondary">{t("shareDialog.noUserShares")}</p>
            ) : (
              <AccessList label={t("shareDialog.tabPeople")}>
                {userShares.map((u) => (
                  <AccessRow
                    key={u.id}
                    title={u.display_name || u.email}
                    detail={u.display_name ? <span className="truncate">{u.email}</span> : undefined}
                    badge={<Badge tone={u.role === "editor" ? "accent" : "neutral"}>{t(u.role === "editor" ? "shareDialog.roleEditor" : "shareDialog.roleViewer")}</Badge>}
                    actions={
                      <Button variant="ghost" size="sm" onClick={() => void onRevokeUserShare(u)}>
                        {t("shareDialog.revoke")}
                      </Button>
                    }
                  />
                ))}
              </AccessList>
            )}
          </section>
        )}

        {tab === "projects" && canManage(asset) && <ProjectSharesSection asset={asset} />}
      </div>
    </Dialog>
  );
}

function LinkRow({ share: s, copied, onCopy, onRevoke }: { share: ShareLink; copied: boolean; onCopy: () => void; onRevoke: () => void }) {
  const info = MODE_INFO[s.mode];
  return (
    <AccessRow
      muted={Boolean(s.revoked_at)}
      title={
        <span className="flex items-center gap-1.5">
          <info.icon size={14} aria-hidden className="shrink-0 text-text-secondary" />
          {t(info.label)}
        </span>
      }
      detail={
        <>
          <code className="min-w-0 max-w-full truncate font-code text-caption text-text-primary">{s.url}</code>
          {s.expires_at && <span>{t("shareDialog.expires", { date: formatShortDate(s.expires_at) })}</span>}
          {s.mode === "magic_email" && s.allowed_emails && <span>{tn("shareDialog.recipients", s.allowed_emails.length)}</span>}
          <ViewCounter share={s} />
          {s.revoked_at && <span className="text-danger">{t("shareDialog.revoked")}</span>}
        </>
      }
      actions={
        !s.revoked_at && (
          <>
            <Button variant="secondary" size="sm" icon={copied ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />} onClick={onCopy}>
              {copied ? t("secretReveal.copied") : t("secretReveal.copy")}
            </Button>
            <IconButton size="sm" label={t("shareDialog.revokeLinkConfirm")} icon={<Link2Off size={15} aria-hidden />} onClick={onRevoke} />
          </>
        )
      }
    />
  );
}

function ViewCounter({ share }: { share: ShareLink }) {
  if (share.max_views == null) return <span className="tabular-nums">{t("shareDialog.views", { count: share.view_count })}</span>;
  const exhausted = share.view_count >= share.max_views;
  return (
    <span
      className={clsx("tabular-nums", exhausted && "font-medium text-danger")}
      title={share.max_views === 1 ? t("shareDialog.oneTimeTitle") : t("shareDialog.viewLimit")}
    >
      {share.view_count}/{share.max_views} {exhausted ? `· ${t("shareDialog.exhausted")}` : ""}
    </span>
  );
}
