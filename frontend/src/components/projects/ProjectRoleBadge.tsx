import { Crown, Eye, PenLine, ShieldCheck } from "lucide-react";
import type { ProjectRole } from "../../api";
import { t } from "../../lib/i18n";
import { PROJECT_ROLE_LABEL } from "../../lib/roles";
import { Badge } from "../ui/Badge";

const ICON = { owner: Crown, editor: PenLine, viewer: Eye } as const;

/** Your role in a project, as information. No membership (an admin
 * looking in) says so in words instead of looking like a missing value. */
export function ProjectRoleBadge({ role }: { role: ProjectRole | null }) {
  if (!role)
    return (
      <Badge icon={<ShieldCheck size={12} aria-hidden />} title={t("projects.noRoleTitle")}>
        {t("projects.noRole")}
      </Badge>
    );
  const Icon = ICON[role];
  return (
    <Badge tone={role === "owner" ? "accent" : "neutral"} icon={<Icon size={12} aria-hidden />}>
      {t(PROJECT_ROLE_LABEL[role])}
    </Badge>
  );
}
