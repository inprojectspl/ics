import { useState } from "react";
import { clsx } from "clsx";
import { Star } from "lucide-react";
import { api } from "../api";
import { t } from "../lib/i18n";

interface Props {
  assetId: string;
  pinned: boolean;
  /** Called after the API call settles, with the new pinned state so the
   * caller can fire a toast / refresh / etc. */
  onToggled: (pinned: boolean) => void;
}

/**
 * Favorite toggle - a star. Filled orange `accent` when pinned, quiet
 * outline otherwise. The star metaphor reads instantly as "favorite".
 */
export function PinButton({ assetId, pinned, onToggled }: Props) {
  const [busy, setBusy] = useState(false);

  const toggle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (busy) return;
    setBusy(true);
    try {
      if (pinned) {
        await api.unpinAsset(assetId);
        onToggled(false);
      } else {
        await api.pinAsset(assetId);
        onToggled(true);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      aria-pressed={pinned}
      aria-label={pinned ? t("pinButton.remove") : t("pinButton.add")}
      title={pinned ? t("pinButton.remove") : t("pinButton.add")}
      className={clsx(
        // Match the IconAction box exactly (min-w-9 min-h-9 p-2 rounded-control)
        // so the star lines up with the other row icons.
        "shrink-0 inline-flex items-center justify-center min-w-9 min-h-9 p-2 rounded-control",
        "transition-[color,background-color,transform] duration-150 ease-standard active:scale-90",
        pinned
          ? "text-accent hover:bg-surface-subtle/80"
          : "text-text-tertiary/70 hover:text-text-secondary hover:bg-surface-subtle/80",
        "disabled:opacity-50",
      )}
    >
      <Star
        size={16}
        aria-hidden
        fill={pinned ? "currentColor" : "none"}
        strokeWidth={pinned ? 0 : 1.75}
      />
    </button>
  );
}
