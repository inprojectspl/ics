import { clsx } from "clsx";
import { KeyRound, LogOut, Settings } from "lucide-react";
import { api, type Me } from "../../api";
import { t } from "../../lib/i18n";
import { initials } from "../../lib/initials";
import { USER_ROLE_LABEL } from "../../lib/roles";
import { AppLink } from "../ui/AppLink";
import { Popover } from "../ui/Popover";
import { Preferences } from "./Preferences";

const ROW =
  "flex min-h-10 w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-ui text-text-primary transition-colors duration-150 hover:bg-surface-hover";

/**
 * Everything about the signed-in person, in one place: who they are,
 * their settings, how the app looks and speaks, and signing out. Theme and
 * language live here, not as permanent buttons in the bar.
 */
export function AccountMenu({ me }: { me: Me }) {
  const name = me.display_name?.trim() || me.email;

  // A full reload rather than a state reset: it drops every cached query of the old session.
  const logout = async () => {
    await api.logout();
    window.location.assign("/");
  };

  return (
    <Popover
      label={t("userMenu.open")}
      align="end"
      widthClass="w-80"
      trigger={(props) => (
        <button
          type="button"
          {...props}
          aria-label={t("userMenu.open")}
          title={me.email}
          className="group/avatar relative inline-flex size-9 items-center justify-center rounded-full"
        >
          <span
            aria-hidden
            className="inline-flex size-8 items-center justify-center rounded-full bg-surface-subtle text-meta font-semibold text-text-primary ring-1 ring-border transition-[box-shadow,background-color] duration-150 group-hover/avatar:bg-surface-hover group-hover/avatar:ring-2 group-hover/avatar:ring-border-strong group-aria-expanded/avatar:ring-2 group-aria-expanded/avatar:ring-accent"
          >
            {initials(me.display_name, me.email)}
          </span>
        </button>
      )}
    >
      {({ close }) => (
        <div className="space-y-3">
          <div className="flex items-center gap-3 px-1 pt-1">
            <span
              aria-hidden
              className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-surface-subtle text-ui font-semibold text-text-primary ring-1 ring-border"
            >
              {initials(me.display_name, me.email)}
            </span>
            <div className="min-w-0">
              <p className="truncate text-body font-semibold text-text-primary">{name}</p>
              {name !== me.email && <p className="truncate text-meta text-text-secondary">{me.email}</p>}
              <p className="text-meta text-text-secondary">
                {t(USER_ROLE_LABEL[me.role])}
                {me.dev_stub_sso ? " · dev-stub" : ""}
              </p>
            </div>
          </div>

          <div className="border-t border-border pt-2">
            <AppLink href="/account/notifications" onClick={close} className={ROW}>
              <Settings size={16} aria-hidden className="text-text-secondary" />
              {t("account.menu")}
            </AppLink>
            <AppLink href="/account/tokens" onClick={close} className={ROW}>
              <KeyRound size={16} aria-hidden className="text-text-secondary" />
              {t("accessTokens.menu")}
            </AppLink>
          </div>

          <div className="border-t border-border px-1 pt-3">
            <Preferences saveLocale />
          </div>

          {!me.dev_stub_sso && (
            <div className="border-t border-border pt-2">
              <button type="button" onClick={() => void logout()} className={clsx(ROW, "text-text-primary")}>
                <LogOut size={16} aria-hidden className="text-text-secondary" />
                {t("common.signOut")}
              </button>
            </div>
          )}
        </div>
      )}
    </Popover>
  );
}
