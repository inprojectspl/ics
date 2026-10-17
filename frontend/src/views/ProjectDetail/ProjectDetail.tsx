import { useCallback, useEffect, useState } from "react";
import { LogOut, MoreHorizontal, Pencil, ShieldOff, Trash2, UploadCloud, UserPlus } from "lucide-react";
import { api, Me, ProjectDetail as P } from "../../api";
import { EmptyState } from "../../components/EmptyState";
import { LoadingListSkeleton } from "../../components/LoadingListSkeleton";
import { ProjectWatchToggle } from "../../components/WatchToggle";
import { DropOverlay } from "../../components/documents/DropOverlay";
import { UploadDialog } from "../../components/documents/UploadDialog";
import { ProjectFrame } from "../../components/projects/ProjectFrame";
import type { ProjectTab } from "../../components/ProjectTabs";
import { Page } from "../../components/shell/Page";
import { PageContext } from "../../components/shell/PageContext";
import { Button } from "../../components/ui/Button";
import { iconButtonClass } from "../../components/ui/IconButton";
import { Menu } from "../../components/ui/Menu";
import type { MenuAction } from "../../components/ui/menuAction";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { useAssetSort } from "../../lib/useAssetSort";
import { useAssetUpload } from "../../lib/useAssetUpload";
import { useLocation } from "../../lib/useLocation";
import { useUploadMode } from "../../lib/uploadMode";
import { EditProjectDialog } from "./EditProjectDialog";
import { InviteMemberDialog } from "./InviteMemberDialog";
import { ProjectDocuments } from "./ProjectDocuments";
import { ProjectLinks } from "./ProjectLinks";
import { ProjectMembers } from "./ProjectMembers";
import { useProjectMutations } from "./useProjectMutations";

interface Props {
  me: Me;
  slug: string;
}

type LocalTab = Extract<ProjectTab, "files" | "members" | "settings">;

function localTab(search: URLSearchParams): LocalTab {
  const tab = search.get("tab");
  return tab === "members" || tab === "settings" ? tab : "files";
}

/**
 * One project. Its documents are the page; the people and the settings are
 * local tabs of the same address, the map, upkeep and agent context the
 * project's other views. Everything the project can do sits in the header:
 * invite, upload, and the rest in `…`.
 */
export function ProjectDetail({ me, slug }: Props) {
  const [project, setProject] = useState<P | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"upload" | "invite" | "edit" | null>(null);
  const [uploadMode, setUploadMode] = useUploadMode();
  const { sort, setSort } = useAssetSort("project", me.id);
  const tab = localTab(useLocation().search);

  // The server applies the sort too, so a project over the 200-row cap
  // returns the right first rows for the chosen order.
  const refresh = useCallback(
    () => api.getProject(slug, sort).then(setProject, (e) => setError(formatApiError(e))),
    [slug, sort],
  );
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const mutations = useProjectMutations(project, refresh);
  // Uploads from here land in this project; the backend checks the role.
  const { uploading, onDrop, onPicked } = useAssetUpload({ uploadMode, projectId: project?.id, onUploaded: refresh });

  if (error) {
    return (
      <>
        <PageContext crumbs={[{ label: t("nav.projects"), href: "/projects" }, { label: t("viewerStates.noAccess") }]} />
        <Page width="form">
          <EmptyState icon={ShieldOff} title={t("viewerStates.noAccess")} description={error} />
        </Page>
      </>
    );
  }

  const admin = me.role === "admin";
  const isOwner = project?.my_role === "owner" || admin;
  const canContribute = isOwner || project?.my_role === "editor";
  const member = Boolean(project?.my_role) || admin;
  const busy = mutations.pending !== null;

  const more: MenuAction[] = [];
  if (project && isOwner) more.push({ key: "edit", label: t("projectHeader.editTitle"), icon: Pencil, onClick: () => setDialog("edit") });
  if (project?.my_role && project.my_role !== "owner")
    more.push({ key: "leave", label: t("projectDetail.leave"), icon: LogOut, danger: true, onClick: () => void mutations.leave() });
  if (project && isOwner)
    more.push({ key: "delete", label: t("projectDetail.deleteProject"), icon: Trash2, danger: true, onClick: () => void mutations.remove() });

  const actions = project && (
    <>
      {isOwner && (
        <Button variant="secondary" icon={<UserPlus size={16} aria-hidden />} onClick={() => setDialog("invite")} disabled={busy}>
          {t("common.invite")}
        </Button>
      )}
      {canContribute && (
        <Button icon={<UploadCloud size={16} aria-hidden />} onClick={() => setDialog("upload")}>
          {t("upload.action")}
        </Button>
      )}
      {more.length > 0 && (
        <Menu
          label={t("projectDetail.moreActions", { name: project.name })}
          actions={more}
          trigger={(props) => (
            <button type="button" {...props} aria-label={t("projectDetail.moreActions", { name: project.name })} className={iconButtonClass("secondary")}>
              <MoreHorizontal size={18} aria-hidden />
            </button>
          )}
        />
      )}
    </>
  );

  return (
    <ProjectFrame
      me={me}
      slug={slug}
      tab={tab}
      actions={actions}
      contextActions={member ? <ProjectWatchToggle slug={slug} /> : undefined}
    >
      {!project ? (
        <LoadingListSkeleton rows={5} />
      ) : tab === "members" ? (
        <ProjectMembers me={me} project={project} canManage={isOwner} mutations={mutations} />
      ) : tab === "settings" && isOwner ? (
        <ProjectLinks slug={project.slug} canEdit={isOwner} />
      ) : (
        <ProjectDocuments
          project={project}
          sort={sort}
          onSortChange={setSort}
          canContribute={canContribute}
          onChanged={refresh}
        />
      )}

      {project && canContribute && (
        <DropOverlay
          target={project.name}
          audience={t(uploadMode === "public" ? "upload.modePublicBody" : "upload.modeOrgBody")}
          onDrop={(dt) => void onDrop(dt)}
          disabled={dialog !== null}
        />
      )}
      {project && dialog === "upload" && (
        <UploadDialog
          mode={uploadMode}
          onModeChange={setUploadMode}
          uploading={uploading}
          onPicked={onPicked}
          onDrop={onDrop}
          onClose={() => setDialog(null)}
          projectName={project.name}
        />
      )}
      {project && dialog === "invite" && (
        <InviteMemberDialog
          projectName={project.name}
          busy={mutations.pending === "invite"}
          onInvite={mutations.invite}
          onClose={() => setDialog(null)}
        />
      )}
      {project && dialog === "edit" && (
        <EditProjectDialog
          name={project.name}
          description={project.description}
          busy={mutations.pending === "meta"}
          onSave={mutations.saveMeta}
          onClose={() => setDialog(null)}
        />
      )}
    </ProjectFrame>
  );
}
