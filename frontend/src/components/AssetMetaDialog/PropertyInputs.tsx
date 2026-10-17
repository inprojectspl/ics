
import { t } from "../../lib/i18n";
import { Field, inputClass } from "../Field";
import type { PropertiesForm, PropertyField } from "./propertiesForm";

interface Props {
  form: PropertiesForm;
  inputs: Readonly<Record<string, string>>;
  /** Form control key the server or validation flagged (`properties.<name>`). */
  invalid: string | null;
  onChange: (name: string, value: string) => void;
}

const INPUT_TYPE: Record<PropertyField["kind"], string> = {
  text: "text",
  date: "date",
  number: "text",
  list: "text",
};

/** Fields of the doc type's `properties`, rebuilt whenever the type changes. */
export function PropertyInputs({ form, inputs, invalid, onChange }: Props) {
  if (form.fields.length === 0 && form.unsupported.length === 0) return null;
  return (
    <fieldset className="space-y-3 border-t border-border pt-3">
      <legend className="text-meta text-text-secondary font-medium">
        {t("assetMetaDialog.properties")}
      </legend>
      {form.fields.map((f) => {
        const bad = invalid === `properties.${f.name}`;
        return (
          <Field
            key={f.name}
            label={f.required ? `${f.label} *` : f.label}
            hint={f.kind === "list" ? t("assetMetaDialog.listHint") : f.description}
          >
            <input
              type={INPUT_TYPE[f.kind]}
              inputMode={f.kind === "number" ? "decimal" : undefined}
              value={inputs[f.name] ?? ""}
              aria-invalid={bad || undefined}
              onChange={(e) => onChange(f.name, e.target.value)}
              className={inputClass({ size: "lg", invalid: bad })}
            />
          </Field>
        );
      })}
      {form.unsupported.length > 0 && (
        <p className="text-meta text-text-tertiary">
          {t("assetMetaDialog.unsupported", { names: form.unsupported.join(", ") })}
        </p>
      )}
    </fieldset>
  );
}
