import { FormEvent, useEffect, useState } from "react";
import { clsx } from "clsx";
import { api, AuthConfig } from "../api";
import { CardHeading, CenteredCard, Field, PrimaryButton } from "../components/Form";
import { buttonClass } from "../components/ui/Button";
import { t } from "../lib/i18n";
import { safeNextPath } from "../lib/nextPath";

type Props = { onLogged: () => void; next?: string };

const CONFIG_RETRIES = 5;

export function Login({ onLogged, next }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cfg, setCfg] = useState<AuthConfig | null>(null);
  const nextPath = safeNextPath(next);
  const googleHref = `/api/auth/google/login${nextPath ? `?next=${encodeURIComponent(nextPath)}` : ""}`;

  // Retried with backoff (about 30 s in all): an answer lost while the
  // server restarts would otherwise hide Google sign-in until a reload.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = (attempt: number) => {
      api
        .authConfig()
        .then((c) => !cancelled && setCfg(c))
        .catch(() => {
          if (!cancelled && attempt < CONFIG_RETRIES) {
            timer = setTimeout(() => load(attempt + 1), 1000 * 2 ** attempt);
          }
        });
    };
    load(0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.login(email, password);
      // An OAuth consent URL is a backend route: updating SPA history would
      // render Home instead of continuing the authorization request.
      if (nextPath) window.location.assign(nextPath);
      else onLogged();
    } catch {
      setError(t("login.invalidCredentials"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <CenteredCard>
      <CardHeading title={t("login.title")} lead={t("login.lead")} />

      {cfg?.google_oidc_enabled && (
        <>
          <a href={googleHref} className={clsx(buttonClass("secondary", "lg"), "w-full")}>
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path fill="#EA4335" d="M12 5c1.6 0 3 .5 4.2 1.5l3-3A11.5 11.5 0 0 0 .8 7.7l3.6 2.8C5.3 7.3 8.4 5 12 5z" />
              <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.5-.2-2.3H12v4.5h6.4c-.3 1.5-1.1 2.7-2.4 3.6l3.6 2.8c2.1-2 3.4-4.9 3.4-8.6z" />
              <path fill="#FBBC05" d="M4.4 14.3c-.2-.6-.4-1.4-.4-2.3s.1-1.7.4-2.3L.8 6.9A11.5 11.5 0 0 0 0 12c0 1.8.4 3.6 1.2 5.1l3.2-2.8z" />
              <path fill="#34A853" d="M12 23c3.2 0 5.9-1 7.9-2.8l-3.6-2.8c-1 .7-2.3 1.1-4.3 1.1-3.6 0-6.7-2.3-7.7-5.5L.8 16c1.6 3.7 5.3 7 11.2 7z" />
            </svg>
            {t("login.google")}
          </a>
          <div className="my-5 flex items-center gap-3 text-meta text-text-secondary">
            <span className="h-px flex-1 bg-border" />
            <span>{t("login.or")}</span>
            <span className="h-px flex-1 bg-border" />
          </div>
        </>
      )}

      <form onSubmit={onSubmit} className="space-y-4">
        <Field label={t("common.email")} type="email" value={email} onChange={setEmail} autoComplete="username" />
        <Field label={t("common.password")} type="password" value={password} onChange={setPassword} autoComplete="current-password" />
        {error && (
          <p role="alert" className="text-ui text-danger">
            {error}
          </p>
        )}
        <PrimaryButton type="submit" busy={busy}>
          {busy ? t("login.submitting") : t("common.signIn")}
        </PrimaryButton>
      </form>

      <div className="mt-6 flex flex-wrap justify-between gap-2 text-meta">
        <a href="#reset-request" className="text-accent hover:underline">
          {t("login.forgotPassword")}
        </a>
        {cfg?.self_register_enabled ? (
          <a href="#register" className="text-accent hover:underline">
            {t("login.register")}
          </a>
        ) : (
          <span className="text-text-secondary">{t("login.noAccount")}</span>
        )}
      </div>
    </CenteredCard>
  );
}
