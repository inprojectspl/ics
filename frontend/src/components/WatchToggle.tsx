import { clsx } from "clsx";
import { BellOff, Eye } from "lucide-react";
import {
  clearAssetWatch,
  clearProjectWatch,
  getAssetWatch,
  getProjectWatch,
  setAssetWatch,
  setProjectWatch,
} from "../api/notifications";
import type { AssetWatch, ProjectWatch } from "../api/notificationTypes";
import { t } from "../lib/i18n";
import { useOptimisticQuery } from "../lib/notifications/useOptimisticUpdate";
import { qk } from "../lib/queries";
import { useErrorToast } from "./Toast";
import { buttonClass } from "./ui/Button";

interface Step<T> {
  /** The cached value right after the click. */
  next: T;
  request: () => Promise<T>;
}

/** The user hears about this document: watched, or through the project or
 * ownership and not muted. */
export function assetWatchActive(w: AssetWatch): boolean {
  if (w.level === "watch") return true;
  return w.level !== "mute" && (w.via_project !== null || w.own);
}

/** What a click does. Active only through the project or ownership: mute
 * (the watch cannot be dropped). Muted: unmute. Otherwise watch or unwatch. */
function assetWatchStep(assetId: string, w: AssetWatch): Step<AssetWatch> {
  const inherited = w.via_project !== null || w.own;
  if (assetWatchActive(w)) {
    return w.level === "watch" && !inherited
      ? { next: { ...w, level: null }, request: () => clearAssetWatch(assetId) }
      : { next: { ...w, level: "mute" }, request: () => setAssetWatch(assetId, "mute") };
  }
  return w.level === "mute"
    ? { next: { ...w, level: null }, request: () => clearAssetWatch(assetId) }
    : { next: { ...w, level: "watch" }, request: () => setAssetWatch(assetId, "watch") };
}

/** Tooltip and accessible name: the current state and what a click does. */
export function assetWatchTitle(w: AssetWatch, projectName: string | null): string {
  if (w.level === "mute") return t("watch.mutedTitle");
  if (w.level === "watch" && w.via_project === null && !w.own) return t("watch.watchingTitle");
  if (w.level !== "watch" && w.via_project !== null) {
    return projectName ? t("watch.viaProjectTitle", { project: projectName }) : t("watch.viaProjectAnyTitle");
  }
  if (w.level !== "watch" && w.own) return t("watch.ownTitle");
  // Watched directly and also through the project or ownership.
  if (w.level === "watch") return t("watch.watchingInheritedTitle");
  return t("watch.notWatchingTitle");
}

function EyeButton({
  active,
  muted = false,
  title,
  onClick,
}: {
  active: boolean;
  muted?: boolean;
  title: string;
  onClick: () => void;
}) {
  const Icon = muted ? BellOff : Eye;
  return (
    <button
      type="button"
      aria-pressed={active}
      title={title}
      onClick={onClick}
      className={clsx(buttonClass("ghost", "sm"), "px-2.5", active && "text-accent hover:text-accent")}
    >
      <Icon size={16} aria-hidden fill={active ? "currentColor" : "none"} fillOpacity={active ? 0.2 : 0} />
      <span className="max-sm:sr-only">{t(muted ? "watch.muted" : active ? "watch.watching" : "watch.watch")}</span>
      <span className="sr-only">. {title}</span>
    </button>
  );
}

/** The document's watch toggle in the reader's chrome bar, optimistic. */
export function AssetWatchToggle({ assetId, projectName }: { assetId: string; projectName: string | null }) {
  const onError = useErrorToast();
  const { data, write } = useOptimisticQuery<AssetWatch>(
    qk.assetWatch(assetId),
    () => getAssetWatch(assetId),
    onError,
  );
  if (!data) return null;
  const step = assetWatchStep(assetId, data);
  return (
    <EyeButton
      active={assetWatchActive(data)}
      muted={data.level === "mute"}
      title={assetWatchTitle(data, projectName)}
      onClick={() => void write(step.next, step.request)}
    />
  );
}

/** The project's watch toggle in the project page's chrome bar: all
 * activity or nothing (the "new documents" level stays in the API). */
export function ProjectWatchToggle({ slug }: { slug: string }) {
  const onError = useErrorToast();
  const { data, write } = useOptimisticQuery<ProjectWatch>(
    qk.projectWatch(slug),
    () => getProjectWatch(slug),
    onError,
  );
  if (!data) return null;
  const active = data.level !== null;
  return (
    <EyeButton
      active={active}
      title={t(active ? "projectWatch.watchingTitle" : "projectWatch.notWatchingTitle")}
      onClick={() =>
        void (active
          ? write({ level: null }, () => clearProjectWatch(slug))
          : write({ level: "all" }, () => setProjectWatch(slug, "all")))
      }
    />
  );
}
