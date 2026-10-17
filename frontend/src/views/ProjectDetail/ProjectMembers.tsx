import { Crown, UserMinus } from "lucide-react";
import type { Me, ProjectDetail, ProjectMemberRow } from "../../api";
import { ProjectRoleBadge } from "../../components/projects/ProjectRoleBadge";
import { Badge } from "../../components/ui/Badge";
import { DATA_ROW, DataList } from "../../components/ui/DataList";
import { Menu } from "../../components/ui/Menu";
import type { MenuAction } from "../../components/ui/menuAction";
import { t } from "../../lib/i18n";
import { initials } from "../../lib/initials";
import type { ProjectMutations } from "./useProjectMutations";

interface Props {
  me: Me;
  project: ProjectDetail;
  /** Owner or admin: changes roles, hands over and removes people. */
  canManage: boolean;
  mutations: ProjectMutations;
}

/** The people of a project: who they are, their role, and for an owner the
 * role switch and the rest in the row menu. */
export function ProjectMembers({ me, project, canManage, mutations }: Props) {
  const { pending } = mutations;
  const busy = pending !== null;
  return (
    <DataList label={t("projectTabs.members")}>
      {project.members.map((m) => {
        const self = m.user_id === me.id;
        const manageable = canManage && !self && m.role !== "owner";
        return (
          <li key={m.id} className={DATA_ROW}>
            <span
              aria-hidden
              className="grid size-9 shrink-0 place-items-center rounded-full bg-surface-subtle text-meta font-semibold text-text-secondary ring-1 ring-inset ring-border"
            >
              {initials(m.display_name, m.email)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-item font-medium text-text-primary">
                {m.display_name || m.email}
                {self && <span className="ml-1.5 font-normal text-text-secondary">{t("projectDetail.you")}</span>}
              </p>
              <p className="truncate text-meta text-text-secondary">{m.email}</p>
            </div>
            {!m.accepted_at && <Badge tone="warning">{t("projectMembers.pending")}</Badge>}
            {manageable ? (
              <RoleSelect member={m} disabled={busy} onChange={(role) => void mutations.changeRole(m, role)} />
            ) : (
              <ProjectRoleBadge role={m.role} />
            )}
            {manageable ? (
              <Menu
                label={t("projectMembers.actions", { name: m.display_name || m.email })}
                actions={memberActions(m, mutations)}
              />
            ) : (
              canManage && <span aria-hidden className="size-8 shrink-0" />
            )}
          </li>
        );
      })}
    </DataList>
  );
}

function memberActions(m: ProjectMemberRow, mutations: ProjectMutations): MenuAction[] {
  const out: MenuAction[] = [];
  if (m.accepted_at)
    out.push({ key: "transfer", label: t("projectMembers.transfer"), icon: Crown, onClick: () => void mutations.transfer(m) });
  out.push({ key: "kick", label: t("projectMembers.remove"), icon: UserMinus, danger: true, onClick: () => void mutations.kick(m) });
  return out;
}

function RoleSelect({
  member,
  disabled,
  onChange,
}: {
  member: ProjectMemberRow;
  disabled: boolean;
  onChange: (role: "editor" | "viewer") => void;
}) {
  return (
    <select
      value={member.role}
      disabled={disabled}
      aria-label={t("projectMembers.roleOf", { name: member.display_name || member.email })}
      onChange={(e) => onChange(e.target.value as "editor" | "viewer")}
      className="h-8 shrink-0 rounded-control border border-border-strong bg-surface px-2 text-ui text-text-primary disabled:opacity-50"
    >
      <option value="editor">{t("common.roleEditor")}</option>
      <option value="viewer">{t("common.roleViewer")}</option>
    </select>
  );
}
