import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, type ProjectDetail, type ProjectMemberRow } from "../../api";
import { useConfirm } from "../../components/ConfirmDialog";
import { useToast } from "../../components/Toast";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { navigate } from "../../lib/navigate";
import { qk } from "../../lib/queries";

/**
 * Every change a project page can make. `pending` names the one in flight
 * ("invite", "kick:<uid>", "role:<uid>", "transfer:<uid>", "leave", "delete",
 * "meta") so the page shows progress on that control only.
 */
export function useProjectMutations(project: ProjectDetail | null, refresh: () => Promise<unknown>) {
  const [pending, setPending] = useState<string | null>(null);
  const { toast } = useToast();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const slug = project?.slug ?? "";

  // The sidebar and the project list hold the name, role and counts too.
  const refreshAll = useCallback(async () => {
    await Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: qk.projects() })]);
  }, [refresh, queryClient]);

  const run = useCallback(
    async (key: string, work: () => Promise<void>, fallback?: string) => {
      if (pending) return false;
      setPending(key);
      try {
        await work();
        return true;
      } catch (err) {
        toast(formatApiError(err, fallback), "error");
        return false;
      } finally {
        setPending(null);
      }
    },
    [pending, toast],
  );

  const invite = (email: string, role: "editor" | "viewer") =>
    run(
      "invite",
      async () => {
        await api.inviteProjectMember(slug, email, role);
        toast(t("projectDetail.inviteSent"), "success");
        await refreshAll();
      },
      t("projectDetail.inviteFailed"),
    );

  const kick = async (m: ProjectMemberRow) => {
    const ok = await confirm({
      title: t("projectDetail.kickTitle", { email: m.email }),
      message: t("projectDetail.kickBody"),
      confirmLabel: t("projectDetail.kickConfirm"),
      destructive: true,
    });
    if (!ok) return;
    await run(`kick:${m.user_id}`, async () => {
      await api.kickProjectMember(slug, m.user_id);
      toast(t("projectDetail.kicked"), "success");
      await refreshAll();
    });
  };

  const changeRole = (m: ProjectMemberRow, role: "editor" | "viewer") =>
    run(`role:${m.user_id}`, async () => {
      await api.patchProjectMember(slug, m.user_id, role);
      await refresh();
    });

  const transfer = async (m: ProjectMemberRow) => {
    const ok = await confirm({
      title: t("projectDetail.transferTitle", { email: m.email }),
      message: t("projectDetail.transferBody"),
      confirmLabel: t("projectDetail.transferConfirm"),
    });
    if (!ok) return;
    await run(`transfer:${m.user_id}`, async () => {
      await api.transferProjectOwner(slug, m.user_id);
      toast(t("projectDetail.transferred"), "success");
      await refreshAll();
    });
  };

  const leave = async () => {
    const ok = await confirm({
      title: t("projectDetail.leaveTitle"),
      message: t("projectDetail.leaveBody"),
      confirmLabel: t("projectDetail.leaveConfirm"),
      destructive: true,
    });
    if (!ok) return;
    await run("leave", async () => {
      await api.leaveProject(slug);
      toast(t("projectDetail.left"), "success");
      await queryClient.invalidateQueries({ queryKey: qk.projects() });
      navigate("/projects");
    });
  };

  const remove = async () => {
    if (!project) return;
    const ok = await confirm({
      title: t("projectDetail.deleteTitle", { name: project.name }),
      message: t("projectDetail.deleteBody"),
      confirmLabel: t("common.delete"),
      destructive: true,
    });
    if (!ok) return;
    await run("delete", async () => {
      await api.deleteProject(slug);
      toast(t("projectDetail.deleted"), "success");
      await queryClient.invalidateQueries({ queryKey: qk.projects() });
      navigate("/projects");
    });
  };

  /** Throws on failure, so the edit dialog stays open for another try. */
  const saveMeta = async (name: string, description: string | null) => {
    setPending("meta");
    try {
      await api.patchProject(slug, { name, description });
      toast(t("projectDetail.saved"), "success");
      await refreshAll();
    } catch (err) {
      toast(formatApiError(err, t("projectDetail.saveFailed")), "error");
      throw err;
    } finally {
      setPending(null);
    }
  };

  return { pending, invite, kick, changeRole, transfer, leave, remove, saveMeta };
}

export type ProjectMutations = ReturnType<typeof useProjectMutations>;
