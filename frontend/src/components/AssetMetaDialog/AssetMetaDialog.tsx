import { useMemo, useState } from "react";
import { clsx } from "clsx";

import { api, type AssetMetaDetail, type AssetMetaView } from "../../api";
import { ApiError } from "../../api/_core";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { useDocTypes } from "../../lib/useDocTypes";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { Field, INPUT_BASE, inputClass } from "../Field";
import { buildChanges, fieldKey, initialDraft, type MetaDraft } from "./metaDraft";
import { buildPropertiesForm, toInput, type PropertiesForm } from "./propertiesForm";
import { PropertyInputs } from "./PropertyInputs";

export interface Person {
  id: string;
  label: string;
}

interface Props {
  assetId: string;
  meta: AssetMetaView;
  /** Who can be picked as maintainer. */
  people: Person[];
  onClose: () => void;
  /** `detail` is null when only the tags changed; `tags` is set when they did. */
  onSaved: (detail: AssetMetaDetail | null, tags: string[] | undefined) => void;
}

// Backend limits (ADR-0015).
export const SUMMARY_MAX = 1000;
const LANGUAGE_MAX = 8;

/** All document metadata in one form; only what changed is sent. */
export function AssetMetaDialog({ assetId, meta, people, onClose, onSaved }: Props) {
  const docTypes = useDocTypes();
  const [draft, setDraft] = useState<MetaDraft>(() => initialDraft(meta));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invalid, setInvalid] = useState<string | null>(null);

  const chosen = docTypes.find((d) => d.key === draft.doc_type);
  // Unknown schema (types still loading, no type chosen): properties stay as stored.
  const form: PropertiesForm | null = useMemo(
    () => (chosen ? buildPropertiesForm(chosen.properties_schema) : null),
    [chosen],
  );
  // Properties are sent only when the type changed or a property was edited,
  // so saving a summary never rewrites values the form does not show.
  const propertiesTouched =
    draft.doc_type !== (meta.doc_type ?? "") || Object.keys(draft.properties).length > 0;
  const stored = meta.properties ?? {};
  const inputs: Record<string, string> = {};
  for (const f of form?.fields ?? []) {
    inputs[f.name] = draft.properties[f.name] ?? toInput(f, stored[f.name]);
  }

  const set = <K extends keyof MetaDraft>(field: K, value: MetaDraft[K]) =>
    setDraft((d) => ({ ...d, [field]: value }));

  // An archived or unknown current type stays selectable, so opening the
  // dialog never changes the type by itself.
  const typeOptions = docTypes.filter((d) => !d.archived || d.key === meta.doc_type);
  const keepCurrent = meta.doc_type !== null && !typeOptions.some((d) => d.key === meta.doc_type);

  const save = async () => {
    const result = buildChanges(
      { ...draft, properties: inputs },
      meta,
      propertiesTouched ? form : null,
    );
    if (!result.ok) {
      setInvalid(result.invalid[0] ?? null);
      setError(t("assetMetaDialog.invalidProperty"));
      return;
    }
    const { patch, tags } = result.changes;
    if (Object.keys(patch).length === 0 && !tags) {
      onClose();
      return;
    }
    setBusy(true);
    setError(null);
    setInvalid(null);
    try {
      const detail = Object.keys(patch).length ? await api.patchMeta(assetId, patch) : null;
      const saved = tags ? (await api.setTags(assetId, tags)).tags : undefined;
      onSaved(detail, saved);
    } catch (e) {
      setError(formatApiError(e));
      setInvalid(e instanceof ApiError ? fieldKey(e.field) : null);
    } finally {
      setBusy(false);
    }
  };

  const bad = (key: string) => invalid === key;

  return (
    <Dialog eyebrow={t("assetMetaDialog.eyebrow")} title={meta.title ?? meta.slug} onClose={onClose} maxWidth="xl">
      <form
        className="px-6 py-5 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <Field label={t("assetMeta.summaryLabel")}>
          <textarea
            value={draft.summary}
            maxLength={SUMMARY_MAX}
            rows={3}
            aria-invalid={bad("summary") || undefined}
            onChange={(e) => set("summary", e.target.value)}
            className={clsx(INPUT_BASE, "w-full py-2 text-ui leading-relaxed", bad("summary") ? "border-danger" : "border-border-strong")}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("assetMetaDialog.docType")}>
            <select
              value={draft.doc_type}
              aria-invalid={bad("doc_type") || undefined}
              onChange={(e) => set("doc_type", e.target.value)}
              className={inputClass({ size: "lg", invalid: bad("doc_type") })}
            >
              <option value="">{t("assetMetaDialog.noDocType")}</option>
              {keepCurrent && meta.doc_type && <option value={meta.doc_type}>{meta.doc_type}</option>}
              {typeOptions.map((d) => (
                <option key={d.key} value={d.key}>
                  {d.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("assetMeta.maintainer")}>
            <select
              value={draft.maintainer_id}
              aria-invalid={bad("maintainer_id") || undefined}
              onChange={(e) => set("maintainer_id", e.target.value)}
              className={inputClass({ size: "lg", invalid: bad("maintainer_id") })}
            >
              <option value="">{t("assetMetaDialog.maintainerDefault")}</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("assetMeta.reviewDue")}>
            <input
              type="date"
              value={draft.review_date}
              aria-invalid={bad("review_due_at") || undefined}
              onChange={(e) => set("review_date", e.target.value)}
              className={inputClass({ size: "lg", invalid: bad("review_due_at") })}
            />
          </Field>
          <Field label={t("assetMetaDialog.language")}>
            <input
              value={draft.language}
              maxLength={LANGUAGE_MAX}
              placeholder={t("assetMetaDialog.languagePlaceholder")}
              aria-invalid={bad("language") || undefined}
              onChange={(e) => set("language", e.target.value)}
              className={clsx(inputClass({ size: "lg", invalid: bad("language") }), "font-code")}
            />
          </Field>
        </div>
        <Field label={t("assetMetaDialog.tags")} hint={t("assetMetaDialog.tagsHint")}>
          <input
            value={draft.tags}
            onChange={(e) => set("tags", e.target.value)}
            className={clsx(inputClass({ size: "lg" }), "font-code")}
          />
        </Field>

        {form && (
          <PropertyInputs
            form={form}
            inputs={inputs}
            invalid={invalid}
            onChange={(name, value) =>
              setDraft((d) => ({ ...d, properties: { ...d.properties, [name]: value } }))
            }
          />
        )}

        {error && (
          <p role="alert" className="text-ui text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? t("common.saving") : t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
