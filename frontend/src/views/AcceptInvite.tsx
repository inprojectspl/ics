import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, type ProjectInvitation, type ProjectRole } from "../api";
import { CardHeading, CenteredCard } from "../components/Form";
import { AppLink } from "../components/ui/AppLink";
import { Button, buttonClass } from "../components/ui/Button";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { qk } from "../lib/queries";
import { projectRoleName } from "../lib/roles";
import { sessionQuery } from "../lib/useSessionUser";

type Phase =
  | { kind: "checking" }
  | { kind: "need-login" }
  | { kind: "review"; invitation: ProjectInvitation; busy: boolean }
  | { kind: "done"; projectSlug: string; projectName: string; role: ProjectRole }
  | { kind: "declined"; projectName: string }
  | { kind: "error"; message: string };

interface Props {
  slug: string;
  /** From the e-mail link; empty when the inbox entry opens the screen. */
  token: string;
}

/** The accepted invitation; the new project belongs in the sidebar and the list. */
function joined(qc: QueryClient, projectSlug: string, projectName: string, role: ProjectRole): Phase {
  void qc.invalidateQueries({ queryKey: qk.projects() });
  return { kind: "done", projectSlug, projectName, role };
}

/** A card that ends on the way back to the projects list. */
function BackToProjects({ title, lead }: { title: string; lead: string }) {
  return (
    <CenteredCard>
      <CardHeading title={title} lead={lead} />
      <AppLink href="/projects" className={clsx(buttonClass("secondary", "lg"), "w-full")}>
        {t("acceptInvite.backToProjects")}
      </AppLink>
    </CenteredCard>
  );
}

/**
 * Project invite landing page. The e-mail link (with a token) accepts at
 * once: following it is the answer. The inbox entry (no token) shows the
 * invitation with Accept and Decline. No session: go to /#login and come
 * back here. A new account has no password yet; its invite e-mail carries a
 * /setup link for that first.
 */
export function AcceptInvite({ slug, token }: Props) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<Phase>({ kind: "checking" });

  useEffect(() => {
    let cancelled = false;
    const update = (next: Phase) => {
      if (!cancelled) setPhase(next);
    };
    (async () => {
      try {
        // The router has usually loaded the session already.
        await queryClient.fetchQuery(sessionQuery);
      } catch {
        update({ kind: "need-login" });
        return;
      }
      if (cancelled) return;
      try {
        if (!token) {
          const invitation = await api.getProjectInvitation(slug);
          update(
            invitation.accepted
              ? { kind: "done", projectSlug: slug, projectName: invitation.project_name, role: invitation.role }
              : { kind: "review", invitation, busy: false },
          );
          return;
        }
        const r = await api.acceptProjectInvite(token);
        update(
          r.accepted && r.project_slug
            ? joined(queryClient, r.project_slug, r.project_name || r.project_slug, r.role)
            : { kind: "error", message: t("acceptInvite.failed") },
        );
      } catch (err) {
        update({ kind: "error", message: formatApiError(err, t("acceptInvite.failed")) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug, token, queryClient]);

  const answer = async (invitation: ProjectInvitation, accept: boolean) => {
    setPhase({ kind: "review", invitation, busy: true });
    try {
      if (accept) {
        await api.acceptProjectInvitation(slug);
        setPhase(joined(queryClient, slug, invitation.project_name, invitation.role));
      } else {
        await api.declineProjectInvitation(slug);
        setPhase({ kind: "declined", projectName: invitation.project_name });
      }
    } catch (err) {
      setPhase({ kind: "error", message: formatApiError(err, t("acceptInvite.failed")) });
    }
  };

  switch (phase.kind) {
    case "checking":
      return (
        <CenteredCard>
          <p role="status" className="text-center text-ui text-text-secondary">
            {t("acceptInvite.checking")}
          </p>
        </CenteredCard>
      );

    case "need-login": {
      // Keep the original URL so login returns here to finish.
      const back = window.location.pathname + window.location.search;
      return (
        <CenteredCard>
          <CardHeading title={t("acceptInvite.title")} lead={t("acceptInvite.needLogin")} />
          <a href={`/#login?next=${encodeURIComponent(back)}`} className={clsx(buttonClass("primary", "lg"), "w-full")}>
            {t("login.title")}
          </a>
        </CenteredCard>
      );
    }

    case "review": {
      const { invitation, busy } = phase;
      const vars = { project: invitation.project_name, role: projectRoleName(invitation.role) };
      return (
        <CenteredCard>
          <CardHeading
            title={t("acceptInvite.title")}
            lead={
              invitation.invited_by
                ? t("acceptInvite.invitedBy", { ...vars, name: invitation.invited_by })
                : t("acceptInvite.invited", vars)
            }
          />
          <div className="flex flex-col gap-2">
            <Button size="lg" className="w-full" busy={busy} onClick={() => void answer(invitation, true)}>
              {t("acceptInvite.accept")}
            </Button>
            <Button size="lg" variant="ghost" className="w-full" disabled={busy} onClick={() => void answer(invitation, false)}>
              {t("acceptInvite.decline")}
            </Button>
          </div>
        </CenteredCard>
      );
    }

    case "declined":
      return (
        <BackToProjects
          title={t("acceptInvite.declined")}
          lead={t("acceptInvite.declinedBody", { project: phase.projectName })}
        />
      );

    case "error":
      return <BackToProjects title={t("errorBoundary.title")} lead={phase.message} />;

    case "done":
      return (
        <CenteredCard>
          <CardHeading
            title={t("acceptInvite.welcome")}
            lead={
              <>
                {t("acceptInvite.joinedPrefix")} <strong className="text-text-primary">{phase.projectName}</strong>{" "}
                {t("acceptInvite.joinedAs")} <strong className="text-text-primary">{projectRoleName(phase.role)}</strong>.
              </>
            }
          />
          <AppLink href={`/projects/${phase.projectSlug}`} className={clsx(buttonClass("primary", "lg"), "w-full")}>
            {t("acceptInvite.openProject")}
          </AppLink>
        </CenteredCard>
      );
  }
}
