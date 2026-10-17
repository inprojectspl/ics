import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { api } from "../api";
import { CardHeading, CenteredCard } from "../components/Form";
import { buttonClass } from "../components/ui/Button";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";

type Phase =
  | { kind: "checking" }
  | { kind: "need-login" }
  | { kind: "accepting" }
  | { kind: "done"; projectSlug: string; projectName: string; role: string }
  | { kind: "error"; message: string };

interface Props {
  token: string;
}

/**
 * Project invite landing page. Signed in: accept and go to the project.
 * No session: go to /#login and come back here. A new account has no
 * password yet; its invite e-mail carries a /setup link for that first.
 */
export function AcceptInvite({ token }: Props) {
  const [phase, setPhase] = useState<Phase>({ kind: "checking" });

  useEffect(() => {
    let cancelled = false;
    const update = (next: Phase) => {
      if (!cancelled) setPhase(next);
    };
    (async () => {
      try {
        await api.me();
      } catch {
        update({ kind: "need-login" });
        return;
      }
      if (cancelled) return;
      update({ kind: "accepting" });
      try {
        const r = await api.acceptProjectInvite(token);
        if (r.accepted && r.project_slug) {
          update({
            kind: "done",
            projectSlug: r.project_slug,
            projectName: r.project_name || r.project_slug,
            role: r.role,
          });
        } else {
          update({ kind: "error", message: t("acceptInvite.failed") });
        }
      } catch (err) {
        update({ kind: "error", message: formatApiError(err, t("acceptInvite.failed")) });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (phase.kind === "checking" || phase.kind === "accepting") {
    return (
      <CenteredCard>
        <p role="status" className="text-center text-ui text-text-secondary">
          {t("acceptInvite.checking")}
        </p>
      </CenteredCard>
    );
  }

  if (phase.kind === "need-login") {
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

  if (phase.kind === "error") {
    return (
      <CenteredCard>
        <CardHeading title={t("errorBoundary.title")} lead={phase.message} />
        <a href="/projects" className={clsx(buttonClass("secondary", "lg"), "w-full")}>
          {t("acceptInvite.backToProjects")}
        </a>
      </CenteredCard>
    );
  }

  return (
    <CenteredCard>
      <CardHeading
        title={t("acceptInvite.welcome")}
        lead={
          <>
            {t("acceptInvite.joinedPrefix")} <strong className="text-text-primary">{phase.projectName}</strong>{" "}
            {t("acceptInvite.joinedAs")} <strong className="text-text-primary">{phase.role}</strong>.
          </>
        }
      />
      <a href={`/projects/${phase.projectSlug}`} className={clsx(buttonClass("primary", "lg"), "w-full")}>
        {t("acceptInvite.openProject")}
      </a>
    </CenteredCard>
  );
}
