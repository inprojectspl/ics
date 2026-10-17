import type { ReactNode } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { api } from "../../api";
import { setLocale, t, useLocale, type Locale } from "../../lib/i18n";
import { useThemePreference, type ThemePreference } from "../../lib/theme";
import { SegmentedToggle } from "../SegmentedToggle";

/** Theme and language: the account menu and the public pages' bar share it. */
export function Preferences({ saveLocale }: { saveLocale: boolean }) {
  const [theme, setTheme] = useThemePreference();
  const locale = useLocale();
  return (
    <div className="space-y-3">
      <Row label={t("theme.label")}>
        <SegmentedToggle<ThemePreference>
          ariaLabel={t("theme.label")}
          value={theme}
          onChange={setTheme}
          options={[
            { value: "light", label: t("theme.light"), icon: <Sun size={14} aria-hidden /> },
            { value: "dark", label: t("theme.dark"), icon: <Moon size={14} aria-hidden /> },
            { value: "system", label: t("theme.system"), icon: <Monitor size={14} aria-hidden /> },
          ]}
        />
      </Row>
      <Row label={t("language.label")}>
        <SegmentedToggle<Locale>
          ariaLabel={t("language.label")}
          value={locale}
          onChange={(next) => {
            setLocale(next);
            // Best effort: the profile keeps the choice for e-mails.
            if (saveLocale) api.setMyLocale(next).catch(() => {});
          }}
          options={[
            { value: "pl", label: t("language.pl") },
            { value: "en", label: t("language.en") },
          ]}
        />
      </Row>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <span className="block text-meta font-medium text-text-secondary">{label}</span>
      {children}
    </div>
  );
}
