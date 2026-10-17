import { FormEvent, useState } from "react";
import { api } from "../api";
import { CenteredCard, Field, PrimaryButton } from "../components/Form";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { PasswordStrength } from "../components/PasswordStrength";

type Props = { token: string; onDone: () => void };

export function ResetConfirm({ token, onDone }: Props) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.passwordResetConfirm(token, password);
      setDone(true);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <CenteredCard>
        <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("resetConfirm.doneTitle")}</h1>
        <PrimaryButton onClick={onDone}>{t("login.title")}</PrimaryButton>
      </CenteredCard>
    );
  }

  return (
    <CenteredCard>
      <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("resetConfirm.title")}</h1>
      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <Field
            label={t("resetConfirm.password")}
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            minLength={8}
          />
          <PasswordStrength password={password} />
        </div>
        {error && <p className="text-ui text-danger">{error}</p>}
        <PrimaryButton type="submit" busy={busy}>
          {busy ? t("resetConfirm.submitting") : t("resetConfirm.submit")}
        </PrimaryButton>
      </form>
    </CenteredCard>
  );
}
