import { FormEvent, useState } from "react";
import { api } from "../api";
import { CenteredCard, Field, PrimaryButton } from "../components/Form";
import { t } from "../lib/i18n";

export function ResetRequest() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.passwordResetRequest(email);
    } catch {
      /* ignore - generic 200 response by design */
    }
    setSubmitted(true);
  };

  if (submitted) {
    return (
      <CenteredCard>
        <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("resetRequest.sentTitle")}</h1>
        <p className="mb-6 text-center text-ui text-text-secondary">
          {t("resetRequest.sentBody")}
        </p>
        <a href="#login" className="text-meta text-accent hover:underline">
          {t("resetRequest.backToLogin")}
        </a>
      </CenteredCard>
    );
  }

  return (
    <CenteredCard>
      <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("resetRequest.title")}</h1>
      <form onSubmit={onSubmit} className="space-y-4">
        <Field label={t("common.email")} type="email" value={email} onChange={setEmail} autoComplete="email" />
        <PrimaryButton type="submit">
          {t("resetRequest.submit")}
        </PrimaryButton>
      </form>
      <div className="mt-6">
        <a href="#login" className="text-meta text-text-tertiary hover:text-accent">
          {t("resetRequest.backToLogin")}
        </a>
      </div>
    </CenteredCard>
  );
}
