import type { ReactNode } from "react";
import { clsx } from "clsx";

import { Button } from "../../components/ui/Button";
import { t } from "../../lib/i18n";
import {
  INCLUDES,
  MAX_BUDGET,
  MAX_DEPTH,
  MIN_BUDGET,
  readParams,
  type TaskAgentParams,
} from "./params";

const INPUT = clsx(
  "h-10 w-full px-3 rounded-control bg-surface border border-border text-text-primary",
  " text-ui focus:border-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35",
);

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-ui font-medium text-text-primary">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-meta text-text-tertiary">{hint}</span>}
    </label>
  );
}

interface Props {
  slug: string;
  params: TaskAgentParams;
  onSubmit: (params: TaskAgentParams) => void;
}

/** Uncontrolled: the parent remounts it (via `key`) when the applied params change. */
export function TaskAgentForm({ slug, params, onSubmit }: Props) {
  return (
    <form
      aria-label={t("taskAgent.formLabel")}
      className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(readParams(new FormData(e.currentTarget), slug));
      }}
    >
      <Field label={t("taskAgent.wp")} hint={t("taskAgent.wpHint")}>
        <input name="wp" required defaultValue={params.wp} className={INPUT} autoComplete="off" />
      </Field>
      <Field label={t("taskAgent.system")}>
        <select name="system" defaultValue={params.system} className={INPUT}>
          <option value="openproject">{t("taskLinks.kindWorkPackage")}</option>
          <option value="project_standard">{t("taskLinks.kindNode")}</option>
        </select>
      </Field>
      <Field label={t("taskAgent.ancestors")} hint={t("taskAgent.ancestorsHint")}>
        <input
          name="ancestors"
          defaultValue={params.ancestors.join(", ")}
          className={INPUT}
          autoComplete="off"
        />
      </Field>
      <Field label={t("common.project")} hint={t("taskAgent.projectHint")}>
        <input name="project" defaultValue={params.project} className={INPUT} autoComplete="off" />
      </Field>
      <Field label={t("taskAgent.depth")} hint={t("taskAgent.depthHint")}>
        <select name="depth" defaultValue={String(params.depth)} className={INPUT}>
          {Array.from({ length: MAX_DEPTH + 1 }, (_, d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t("taskAgent.budget")} hint={t("taskAgent.budgetHint", { min: MIN_BUDGET, max: MAX_BUDGET })}>
        <input
          name="budget"
          type="number"
          min={MIN_BUDGET}
          max={MAX_BUDGET}
          step={100}
          defaultValue={params.budget}
          className={INPUT}
        />
      </Field>
      <fieldset className="sm:col-span-2 lg:col-span-3 flex flex-wrap items-center gap-x-6 gap-y-2">
        <legend className="sr-only">{t("taskAgent.include")}</legend>
        {INCLUDES.map((inc) => (
          <label key={inc} className="inline-flex items-center gap-2 text-ui text-text-secondary">
            <input
              type="checkbox"
              name="include"
              value={inc}
              defaultChecked={params.include.includes(inc)}
              className="accent-accent"
            />
            {t(inc === "references" ? "taskAgent.includeReferences" : "taskAgent.includeDeliverables")}
          </label>
        ))}
        <Button type="submit" className="ml-auto">
          {t("taskAgent.submit")}
        </Button>
      </fieldset>
    </form>
  );
}
