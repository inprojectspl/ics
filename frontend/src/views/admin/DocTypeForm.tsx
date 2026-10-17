import { FormEvent, useState, type ReactNode } from "react";
import { clsx } from "clsx";

import type { AdminDocType, DocTypeCreate, DocTypeUpdate } from "../../api";
import { Button } from "../../components/ui/Button";
import { Disclosure } from "../../components/ui/Disclosure";
import { Field, INPUT_CLASS, TEXTAREA_CLASS } from "../../components/Field";
import { t, type MessageKey } from "../../lib/i18n";
import {
  DOC_TYPE_KEY,
  createPayload,
  draftOf,
  emptyDraft,
  parseCount,
  parseSchema,
  updatePayload,
  type DocTypeDraft,
} from "./docTypeDraft";

type Props = {
  busy: boolean;
  /** Error from the last save, shown above the buttons. */
  error: string | null;
  onCancel: () => void;
} & (
  | { mode: "create"; onCreate: (body: DocTypeCreate) => void }
  | { mode: "edit"; docType: AdminDocType; onUpdate: (key: string, body: DocTypeUpdate) => void }
);

/** First problem that blocks saving, checked on every render. */
function validate(draft: DocTypeDraft, creating: boolean): MessageKey | null {
  if (creating && !DOC_TYPE_KEY.test(draft.key.trim())) return "adminDocTypes.keyInvalid";
  if (!draft.label_pl.trim() || !draft.label_en.trim()) return "adminDocTypes.labelsRequired";
  if (Number.isNaN(parseCount(draft.default_review_days))) return "adminDocTypes.reviewDaysInvalid";
  if (Number.isNaN(parseCount(draft.position))) return "adminDocTypes.positionInvalid";
  return null;
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-4">
      <legend className="mb-3 text-ui font-semibold text-text-primary">{title}</legend>
      {children}
    </fieldset>
  );
}

/**
 * The body of the doc type dialog, for a new type or an existing one. The
 * dialog mounts it per opening, so the draft never needs syncing with props.
 * The JSON Schema is folded away unless the type already has properties.
 */
export function DocTypeForm(props: Props) {
  const creating = props.mode === "create";
  const [draft, setDraft] = useState<DocTypeDraft>(() =>
    props.mode === "edit" ? draftOf(props.docType) : emptyDraft(),
  );
  // Missing fields are reported only after the first edit, not on an empty form.
  const [touched, setTouched] = useState(false);
  const set = (field: keyof DocTypeDraft) => (value: string) => {
    setTouched(true);
    setDraft((d) => ({ ...d, [field]: value }));
  };

  const schema = parseSchema(draft.properties_schema);
  const schemaError: MessageKey | null = schema.ok
    ? null
    : schema.reason === "syntax"
      ? "adminDocTypes.schemaSyntax"
      : "adminDocTypes.schemaNotObject";
  const problem = schemaError ?? validate(draft, creating);
  const blocked = props.busy || problem !== null;
  const message = schemaError ?? (touched ? problem : null);
  const hasProperties = schema.ok && Object.keys(schema.value).length > 0;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (blocked || !schema.ok) return;
    if (props.mode === "create") {
      props.onCreate(createPayload(draft, schema.value));
    } else {
      props.onUpdate(props.docType.key, updatePayload(draft, schema.value));
    }
  };

  return (
    <form onSubmit={submit} aria-label={creating ? t("adminDocTypes.createTitle") : t("adminDocTypes.editLabel")}>
      <div className="space-y-6 px-5 py-5 sm:px-6">
        <Group title={t("adminDocTypes.groupName")}>
          {creating && (
            <Field label={t("adminDocTypes.keyLabel")} hint={t("adminDocTypes.keyHint")}>
              <input
                autoFocus
                value={draft.key}
                onChange={(e) => set("key")(e.target.value)}
                autoCapitalize="none"
                spellCheck={false}
                className={clsx(INPUT_CLASS, "font-code")}
              />
            </Field>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("adminDocTypes.labelPl")}>
              <input autoFocus={!creating} value={draft.label_pl} onChange={(e) => set("label_pl")(e.target.value)} className={INPUT_CLASS} />
            </Field>
            <Field label={t("adminDocTypes.labelEn")}>
              <input value={draft.label_en} onChange={(e) => set("label_en")(e.target.value)} className={INPUT_CLASS} />
            </Field>
          </div>
        </Group>

        <Group title={t("adminDocTypes.groupUse")}>
          <Field label={t("adminDocTypes.agentHint")} hint={t("adminDocTypes.agentHintHint")}>
            <textarea
              value={draft.agent_hint}
              onChange={(e) => set("agent_hint")(e.target.value)}
              rows={2}
              className={TEXTAREA_CLASS}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("adminDocTypes.reviewDays")} hint={t("adminDocTypes.reviewDaysHint")}>
              <input
                inputMode="numeric"
                value={draft.default_review_days}
                onChange={(e) => set("default_review_days")(e.target.value)}
                className={clsx(INPUT_CLASS, "tabular-nums")}
              />
            </Field>
            <Field label={t("adminDocTypes.position")} hint={t("adminDocTypes.positionHint")}>
              <input
                inputMode="numeric"
                value={draft.position}
                onChange={(e) => set("position")(e.target.value)}
                className={clsx(INPUT_CLASS, "tabular-nums")}
              />
            </Field>
          </div>
        </Group>

        <Disclosure title={t("adminDocTypes.schema")} defaultOpen={hasProperties || schemaError !== null}>
          <Field label={t("adminDocTypes.schemaLabel")} hint={t("adminDocTypes.schemaHint")}>
            <textarea
              value={draft.properties_schema}
              onChange={(e) => set("properties_schema")(e.target.value)}
              rows={8}
              spellCheck={false}
              aria-invalid={schemaError ? true : undefined}
              className={clsx(TEXTAREA_CLASS, "font-code text-meta", schemaError && "border-danger")}
            />
          </Field>
        </Disclosure>
      </div>

      <div className="sticky bottom-0 flex flex-wrap items-center justify-end gap-2 border-t border-border bg-surface px-5 py-3 sm:px-6">
        {(message || props.error) && (
          <p role="alert" className="mr-auto min-w-0 text-ui text-danger">
            {message ? t(message) : props.error}
          </p>
        )}
        <Button variant="ghost" onClick={props.onCancel} disabled={props.busy}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" busy={props.busy} disabled={blocked}>
          {creating ? t("common.create") : t("common.save")}
        </Button>
      </div>
    </form>
  );
}
