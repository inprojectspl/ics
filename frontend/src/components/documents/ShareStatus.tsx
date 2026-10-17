import { Building2, Globe2, KeyRound, Link2Off, ShieldAlert, TriangleAlert } from "lucide-react";
import type { SecurityStatus, ShareMode } from "../../api";
import { t, type MessageKey } from "../../lib/i18n";
import { Badge, type BadgeTone } from "../ui/Badge";

type ShareState = "public" | "password" | "org" | "none";

const STATE: Record<ShareState, { label: MessageKey; title: MessageKey; tone: BadgeTone; icon: typeof Globe2 }> = {
  public: { label: "shareStatus.public", title: "shareStatus.publicTitle", tone: "accent", icon: Globe2 },
  password: { label: "shareStatus.password", title: "shareStatus.passwordTitle", tone: "warning", icon: KeyRound },
  org: { label: "shareStatus.org", title: "shareStatus.orgTitle", tone: "neutral", icon: Building2 },
  none: { label: "shareStatus.none", title: "shareStatus.noneTitle", tone: "neutral", icon: Link2Off },
};

/** The widest audience among the active links decides the state. */
export function shareState(modes: readonly ShareMode[] | readonly string[] | undefined): ShareState {
  if (!modes || modes.length === 0) return "none";
  if (modes.includes("public")) return "public";
  if (modes.includes("password")) return "password";
  return "org";
}

/** Who can open the document through a link: one word and an icon, never
 * colour alone. */
export function ShareStatus({ modes }: { modes: readonly string[] | undefined }) {
  const s = STATE[shareState(modes)];
  const Icon = s.icon;
  return (
    <Badge tone={s.tone} icon={<Icon size={12} aria-hidden />} title={t(s.title)}>
      {t(s.label)}
    </Badge>
  );
}

/** Scanner verdict, shown only when it asks for attention. Hidden after a
 * bypass: the decision is made and the owner cannot change it anyway. */
export function SecurityStatusBadge({ status, bypassed }: { status: SecurityStatus | null | undefined; bypassed?: boolean }) {
  if (!status || status === "clean" || bypassed) return null;
  const critical = status === "critical";
  return (
    <Badge
      tone={critical ? "danger" : "warning"}
      icon={critical ? <ShieldAlert size={12} aria-hidden /> : <TriangleAlert size={12} aria-hidden />}
      title={t(critical ? "securityBadge.criticalTitle" : "securityBadge.warnTitle")}
    >
      {t(critical ? "securityBadge.critical" : "securityBadge.warn")}
    </Badge>
  );
}
