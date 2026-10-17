import { Maximize, Minus, Plus, Settings2 } from "lucide-react";
import { t } from "../../lib/i18n";
import { IconButton } from "../ui/IconButton";

export function Toolbar({
  onZoomIn,
  onZoomOut,
  onFit,
  onToggleSettings,
  settingsOpen,
}: {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onToggleSettings: () => void;
  settingsOpen: boolean;
}) {
  return (
    <div className="absolute right-3 top-3 flex items-center gap-0.5 rounded-control border border-border bg-surface/90 p-0.5 shadow-card backdrop-blur-sm">
      <IconButton size="sm" label={t("vaultGraph.zoomIn")} icon={<Plus size={16} aria-hidden />} onClick={onZoomIn} />
      <IconButton size="sm" label={t("vaultGraph.zoomOut")} icon={<Minus size={16} aria-hidden />} onClick={onZoomOut} />
      <IconButton size="sm" label={t("vaultGraph.fit")} icon={<Maximize size={16} aria-hidden />} onClick={onFit} />
      <span className="mx-0.5 h-4 w-px bg-border" aria-hidden />
      <IconButton
        size="sm"
        variant={settingsOpen ? "subtle" : "ghost"}
        label={t("vaultGraph.settings")}
        aria-pressed={settingsOpen}
        icon={<Settings2 size={16} aria-hidden />}
        onClick={onToggleSettings}
      />
    </div>
  );
}
