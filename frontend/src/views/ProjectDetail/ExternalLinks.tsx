import { FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import { INPUT_CLASS } from "../../components/Field";
import { Button } from "../../components/ui/Button";
import { SettingsSection } from "./KeyDocuments";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { qk } from "../../lib/queries";

/** Same rule as the backend (`_PROJECT_KEY`): an OpenProject identifier. */
const EXTERNAL_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;

interface Props {
  slug: string;
  canEdit: boolean;
}

/** OpenProject identifier of the project; other systems' mappings are kept on save. */
export function ExternalLinks({ slug, canEdit }: Props) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.projectExternalRefs(slug),
    queryFn: () => api.getProjectExternalRefs(slug),
  });
  const refs = query.data ?? null;
  // null until the user types: the field then shows the saved identifier.
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setError] = useState<string | null>(null);
  const error = actionError ?? (query.error ? formatApiError(query.error) : null);

  const current = refs?.find((r) => r.system === "openproject")?.external_id ?? "";
  const value = (draft ?? current).trim();
  const invalid = value !== "" && !EXTERNAL_ID.test(value);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!refs || invalid || busy || value === current) return;
    setBusy(true);
    setError(null);
    try {
      const others = refs.filter((r) => r.system !== "openproject");
      const next = value ? [...others, { system: "openproject" as const, external_id: value }] : others;
      queryClient.setQueryData(qk.projectExternalRefs(slug), await api.putProjectExternalRefs(slug, next));
      setDraft(null);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingsSection
      id="project-external-links"
      title={t("projectLinks.externalTitle")}
      intro={t("projectLinks.externalIntro")}
    >
      {refs === null && !error && <p className="text-meta text-text-secondary">{t("common.loading")}</p>}
      {refs !== null && !canEdit && (
        <p className="text-ui text-text-primary">
          {t("projectLinks.openProject")}:{" "}
          {current ? (
            <code className="font-code">{current}</code>
          ) : (
            <span className="text-text-tertiary">{t("projectLinks.notSet")}</span>
          )}
        </p>
      )}
      {refs !== null && canEdit && (
        <form onSubmit={save} className="flex flex-wrap items-end gap-2 max-w-xl">
          <label className="flex-1 min-w-[12rem]">
            <span className="mb-1.5 block text-ui font-medium text-text-primary">
              {t("projectLinks.openProject")}
            </span>
            <input
              value={draft ?? current}
              maxLength={100}
              placeholder="example-project"
              aria-invalid={invalid || undefined}
              onChange={(e) => setDraft(e.target.value)}
              className={`${INPUT_CLASS} font-code aria-invalid:border-danger`}
            />
          </label>
          <Button type="submit" variant="secondary" disabled={busy || invalid || value === current}>
            {busy ? t("common.saving") : t("projectLinks.saveExternal")}
          </Button>
        </form>
      )}
      {invalid && <p className="text-meta text-danger mt-1">{t("projectLinks.externalInvalid")}</p>}
      {error && (
        <p role="alert" className="text-meta text-danger mt-1">
          {error}
        </p>
      )}
    </SettingsSection>
  );
}
