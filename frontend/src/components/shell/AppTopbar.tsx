import { Menu as MenuIcon, Search } from "lucide-react";
import type { Me } from "../../api";
import { t } from "../../lib/i18n";
import { BrandMark } from "../BrandMark";
import { AppLink } from "../ui/AppLink";
import { IconButton } from "../ui/IconButton";
import { AccountMenu } from "./AccountMenu";
import { NotificationsButton } from "./NotificationsButton";

interface Props {
  me: Me;
  /** Opens the navigation drawer; absent when the sidebar column shows the full tree. */
  onOpenNav?: () => void;
  /** Show the logo in the bar (the sidebar is not there to carry it). */
  showBrand: boolean;
  onOpenSearch: () => void;
}

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/**
 * The global bar: search and commands in the middle, the inbox and the
 * account on the right. No section links: those are the sidebar's job.
 */
export function AppTopbar({ me, onOpenNav, showBrand, onOpenSearch }: Props) {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-surface/95 backdrop-blur supports-[backdrop-filter]:bg-surface/85">
      <div className="flex h-14 items-center gap-2 px-3 sm:px-4 lg:px-6">
        {onOpenNav && (
          <IconButton
            label={t("shell.openNav")}
            icon={<MenuIcon size={20} aria-hidden />}
            onClick={onOpenNav}
            aria-controls="app-nav-drawer"
            className="-ml-1"
          />
        )}
        {showBrand && (
          <AppLink href="/" aria-label={t("chrome.home")} className="mr-1 rounded-control p-1 text-text-primary">
            <BrandMark size={22} />
          </AppLink>
        )}

        <div className="flex min-w-0 flex-1 justify-center">
          <button
            type="button"
            onClick={onOpenSearch}
            aria-haspopup="dialog"
            aria-keyshortcuts={isMac ? "Meta+K" : "Control+K"}
            className="hidden h-9 w-full max-w-xl items-center gap-2.5 rounded-control border border-border bg-surface-subtle px-3 text-left text-ui text-text-secondary transition-colors duration-150 hover:border-border-strong hover:bg-surface sm:flex"
          >
            <Search size={16} aria-hidden className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">{t("palette.trigger")}</span>
            <kbd className="hidden rounded-xs border border-border bg-surface px-1.5 font-code text-caption text-text-secondary md:inline">
              {isMac ? "⌘K" : "Ctrl K"}
            </kbd>
          </button>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <IconButton
            label={t("palette.trigger")}
            icon={<Search size={18} aria-hidden />}
            onClick={onOpenSearch}
            className="sm:hidden"
          />
          <NotificationsButton />
          <AccountMenu me={me} />
        </div>
      </div>
    </header>
  );
}
