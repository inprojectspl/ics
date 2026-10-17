import { clsx } from "clsx";
import {
  ArrowDownAZ,
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
  CalendarPlus,
  ChevronDown,
  History,
  Layers,
  Shapes,
  type LucideIcon,
} from "lucide-react";
import {
  ASSET_SORT_KEYS,
  DEFAULT_ORDER,
  SORT_LABEL,
  orderLabel,
  type AssetSort,
  type AssetSortKey,
  type SortOrder,
} from "../lib/assetSort";
import { t } from "../lib/i18n";
import { buttonClass } from "./ui/Button";
import { Menu } from "./ui/Menu";
import type { MenuAction } from "./ui/menuAction";

const KEY_ICON: Record<AssetSortKey, LucideIcon> = {
  updated: History,
  created: CalendarPlus,
  title: ArrowDownAZ,
  versions: Layers,
  kind: Shapes,
};

const ORDER_ICON: Record<SortOrder, LucideIcon> = {
  desc: ArrowDownWideNarrow,
  asc: ArrowUpNarrowWide,
};

interface Props {
  sort: AssetSort;
  onChange: (next: AssetSort) => void;
  className?: string;
  relevance?: { active: boolean; onSelect: () => void };
}

/**
 * Sort picker of every document list: the key and the direction in one
 * menu (a sheet on phones). Stateless; the caller owns the value
 * (`useAssetSort`).
 */
export function AssetSortControl({ sort, onChange, className, relevance }: Props) {
  const keyLabel = relevance?.active ? t("assetSort.relevance") : t(SORT_LABEL[sort.key]);
  const options: MenuAction[] = [
    ...(relevance ? [{ key: "relevance", label: t("assetSort.relevance"), checked: relevance.active, onClick: relevance.onSelect }] : []),
    ...ASSET_SORT_KEYS.map((key) => ({
      key,
      label: t(SORT_LABEL[key]),
      icon: KEY_ICON[key],
      checked: !relevance?.active && key === sort.key,
      onClick: () => onChange(key === sort.key ? sort : { key, order: DEFAULT_ORDER[key] }),
    })),
    ...(relevance?.active ? [] : (["desc", "asc"] as const)).map((order, i) => ({
      key: `order:${order}`,
      label: t(orderLabel(sort.key, order)),
      icon: ORDER_ICON[order],
      checked: order === sort.order,
      heading: i === 0 ? t("assetSort.direction") : undefined,
      onClick: () => onChange({ ...sort, order }),
    })),
  ];
  const OrderIcon = ORDER_ICON[sort.order];

  return (
    <Menu
      label={t("assetSort.menuLabel")}
      actions={options}
      trigger={(props) => (
        <button
          type="button"
          {...props}
          aria-label={t("assetSort.triggerLabel", { key: relevance?.active ? keyLabel : `${keyLabel}, ${t(orderLabel(sort.key, sort.order))}` })}
          className={clsx(buttonClass("secondary", "md"), "gap-1.5 px-3", className)}
        >
          <OrderIcon size={16} aria-hidden className="text-text-secondary" />
          <span className="hidden text-text-secondary md:inline">{t("assetSort.prefix")}</span>
          <span className="max-sm:sr-only">{keyLabel}</span>
          <ChevronDown size={14} aria-hidden className="text-text-secondary" />
        </button>
      )}
    />
  );
}
