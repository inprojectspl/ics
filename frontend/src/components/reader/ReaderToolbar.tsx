import type { ReactNode } from "react";
import { clsx } from "clsx";
import { Maximize2, Minimize2, Network, PanelRightClose, PanelRightOpen, Pencil, Share2 } from "lucide-react";
import { t } from "../../lib/i18n";
import { navigate } from "../../lib/navigate";
import { useShell } from "../shell/shellContext";
import { Button } from "../ui/Button";
import { IconButton } from "../ui/IconButton";
import { Menu } from "../ui/Menu";
import type { MenuAction } from "../ui/menuAction";

interface Props {
  /** Left side: what is open (kind, version, date) or the view switch of a collection. */
  start?: ReactNode;
  onEdit?: () => void;
  onShare?: () => void;
  /** The `…` menu: every other action, the same list the phone sheet shows. */
  menu: readonly MenuAction[];
  menuLabel: string;
  inspector?: { open: boolean; toggle: () => void; label: string };
  /** The full graph view of this document, for readers with graph access. */
  graphHref?: string;
}

/**
 * One bar with everything the open document can do. Stays under the
 * global bar while reading. Edit and share are labelled (they matter most),
 * the rest is in `…`; reading focus and the inspector are toggles with a
 * visible state.
 */
export function ReaderToolbar({ start, onEdit, onShare, menu, menuLabel, inspector, graphHref }: Props) {
  const { focusMode, setFocusMode, signedIn } = useShell();
  return (
    <div
      role="toolbar"
      aria-label={t("reader.toolbar")}
      className="sticky top-14 z-20 flex h-12 items-center gap-2 border-b border-border bg-surface/95 px-(--gutter) backdrop-blur supports-[backdrop-filter]:bg-surface/85"
    >
      <div className="flex min-w-0 flex-1 items-center gap-2 text-meta text-text-secondary">{start}</div>
      <div className="flex shrink-0 items-center gap-1">
        {onEdit && (
          <Button variant="secondary" size="sm" icon={<Pencil size={15} aria-hidden />} onClick={onEdit}>
            <span className="max-sm:sr-only">{t("common.edit")}</span>
          </Button>
        )}
        {onShare && (
          <Button variant="secondary" size="sm" icon={<Share2 size={15} aria-hidden />} onClick={onShare}>
            <span className="max-sm:sr-only">{t("common.share")}</span>
          </Button>
        )}
        {signedIn && (
          <IconButton
            size="sm"
            className="max-md:hidden"
            label={t(focusMode ? "reader.focusOff" : "reader.focusOn")}
            aria-pressed={focusMode}
            icon={focusMode ? <Minimize2 size={16} aria-hidden /> : <Maximize2 size={16} aria-hidden />}
            onClick={() => setFocusMode(!focusMode)}
          />
        )}
        {graphHref && (
          <IconButton
            size="sm"
            label={t("reader.openGraph")}
            icon={<Network size={16} aria-hidden />}
            onClick={() => navigate(graphHref)}
          />
        )}
        {inspector && (
          <IconButton
            size="sm"
            label={inspector.label}
            aria-expanded={inspector.open}
            aria-controls="reader-inspector"
            className={clsx(inspector.open && "bg-surface-hover text-text-primary")}
            icon={inspector.open ? <PanelRightClose size={16} aria-hidden /> : <PanelRightOpen size={16} aria-hidden />}
            onClick={inspector.toggle}
          />
        )}
        {menu.length > 0 && (
          <Menu
            label={menuLabel}
            actions={menu}
          />
        )}
      </div>
    </div>
  );
}
