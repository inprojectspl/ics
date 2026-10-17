import { useState } from "react";
import { unsubscribeEmail } from "../../api/notifications";
import { CenteredCard, PrimaryButton } from "../../components/Form";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";

type State = "idle" | "busy" | "done";

/**
 * E-mail opt-out from the link in a notification e-mail, without login.
 * The token is sent only after a click: mail scanners open links, and a
 * plain GET must not change anything.
 */
export function NotificationsUnsubscribe({ token }: { token: string }) {
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState<string | null>(null);

  const onConfirm = async () => {
    setState("busy");
    setError(null);
    try {
      await unsubscribeEmail(token);
      setState("done");
    } catch (err) {
      setError(formatApiError(err));
      setState("idle");
    }
  };

  if (state === "done") {
    return (
      <CenteredCard>
        <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("unsubscribe.doneTitle")}</h1>
        <p className="mb-6 text-center text-ui text-text-secondary">{t("unsubscribe.doneBody")}</p>
        <a href="/account/notifications" className="text-meta text-accent hover:underline">
          {t("unsubscribe.settingsLink")}
        </a>
      </CenteredCard>
    );
  }

  return (
    <CenteredCard>
      <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("unsubscribe.title")}</h1>
      <p className="mb-6 text-center text-ui text-text-secondary">{token ? t("unsubscribe.body") : t("unsubscribe.missingToken")}</p>
      {error && (
        <p role="alert" className="text-ui text-danger mb-4">
          {error}
        </p>
      )}
      {token && (
        <PrimaryButton type="button" onClick={() => void onConfirm()} disabled={state === "busy"}>
          {state === "busy" ? t("unsubscribe.busy") : t("unsubscribe.confirm")}
        </PrimaryButton>
      )}
    </CenteredCard>
  );
}
