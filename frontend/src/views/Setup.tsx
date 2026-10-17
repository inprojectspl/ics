import { FormEvent, useState } from "react";
import { api } from "../api";
import { CenteredCard, Field, PrimaryButton } from "../components/Form";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { PasswordStrength } from "../components/PasswordStrength";

type Props = { token: string; onDone: () => void };

export function Setup({ token, onDone }: Props) {
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.setupFromToken(token, password, displayName || undefined);
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
        <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("setup.doneTitle")}</h1>
        <p className="mb-6 text-center text-ui text-text-secondary">{t("setup.doneBody")}</p>
        <PrimaryButton onClick={onDone}>{t("setup.goToLogin")}</PrimaryButton>
      </CenteredCard>
    );
  }

  return (
    <CenteredCard>
      <h1 className="mb-2 text-center text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{t("setup.title")}</h1>
      <p className="mb-6 text-center text-ui text-text-secondary">{t("setup.intro")}</p>
      <form onSubmit={onSubmit} className="space-y-4">
        <Field
          label={t("setup.displayName")}
          type="text"
          value={displayName}
          onChange={setDisplayName}
          required={false}
        />
        <div>
          <Field
            label={t("setup.password")}
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
          {busy ? t("setup.submitting") : t("setup.title")}
        </PrimaryButton>
      </form>
    </CenteredCard>
  );
}
