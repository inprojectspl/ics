import { clsx } from "clsx";
import { SecurityStatus } from "../api";
import { t } from "../lib/i18n";
import { Badge } from "./ui/Badge";

interface Props {
  status: SecurityStatus | null | undefined;
  /** Bypass granted (manually or automatically): the badge stays hidden. */
  bypassed?: boolean;
}

/**
 * Compact inline pill for asset lists. Renders nothing when clean or after a
 * bypass: the owner can no longer act on it, and the findings stay in the
 * asset detail and the admin queue.
 */
export function SecurityBadge({ status, bypassed }: Props) {
  if (!status || status === "clean" || bypassed) return null;

  const isCritical = status === "critical";
  return (
    <Badge
      tone={isCritical ? "danger" : "warning"}
      title={isCritical ? t("securityBadge.criticalTitle") : t("securityBadge.warnTitle")}
      icon={<span aria-hidden className={clsx("size-1.5 rounded-full", isCritical ? "bg-danger" : "bg-warning")} />}
    >
      {isCritical ? t("securityBadge.critical") : t("securityBadge.warn")}
    </Badge>
  );
}
