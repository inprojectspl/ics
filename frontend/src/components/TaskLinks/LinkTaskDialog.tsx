import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type AddExternalRefBody, type ExternalRefRole } from "../../api";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { qk } from "../../lib/queries";
import { Button } from "../ui/Button";
import { Field, inputClass } from "../Field";
import { Dialog } from "../ui/Dialog";
import { ROLE_LABEL } from "./taskRef";

interface Props {
  assetId: string;
  slug: string;
  onClose: () => void;
  onLinked: () => void;
}

type TaskKind = "work_package" | "node";

// Same shapes the backend accepts (`services/external_refs.py`).
const WORK_PACKAGE = /^[0-9]{1,12}$/;
const PS_NODE = /^n-[a-z0-9]{1,64}$/;
const SCOPE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;
const ROLES: readonly ExternalRefRole[] = ["context", "deliverable", "reference"];

const INPUT = inputClass({ size: "lg" });

/** Links the document to an OpenProject work package or a Project Standard node. */
export function LinkTaskDialog({ assetId, slug, onClose, onLinked }: Props) {
  const [kind, setKind] = useState<TaskKind>("work_package");
  const [externalId, setExternalId] = useState("");
  const [scope, setScope] = useState("");
  const [role, setRole] = useState<ExternalRefRole>("context");
  const [required, setRequired] = useState(false);
  const [path, setPath] = useState("");
  const [pinned, setPinned] = useState("");
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Files of a collection come from its outline; other kinds have none.
  const files = useQuery({ queryKey: qk.outline(slug), queryFn: () => api.getOutline(slug) }).data?.files ?? [];

  const id = externalId.trim();
  const idValid = kind === "work_package" ? WORK_PACKAGE.test(id) : PS_NODE.test(id);
  const scopeValid = kind === "work_package" || SCOPE.test(scope.trim());
  const pinnedValid = pinned === "" || /^[1-9][0-9]*$/.test(pinned);
  const valid = idValid && scopeValid && pinnedValid;

  const submit = async () => {
    if (!valid || busy) return;
    const body: AddExternalRefBody =
      kind === "work_package"
        ? { system: "openproject", entity: "work_package", external_id: id }
        : { system: "project_standard", entity: "node", external_id: id, external_scope: scope.trim() };
    body.role = role;
    body.required = required;
    if (path) body.asset_path = path;
    if (pinned) body.pinned_version = Number(pinned);
    if (label.trim()) body.label = label.trim();
    if (url.trim()) body.url = url.trim();
    if (note.trim()) body.note = note.trim();
    setBusy(true);
    setError(null);
    try {
      await api.addExternalRef(assetId, body);
      onLinked();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog eyebrow={t("taskLinks.title")} title={t("taskLinks.dialogTitle")} onClose={onClose} maxWidth="lg">
      <form
        className="px-6 py-5 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label={t("taskLinks.kind")}>
          <select value={kind} onChange={(e) => setKind(e.target.value as TaskKind)} className={INPUT}>
            <option value="work_package">{t("taskLinks.kindWorkPackage")}</option>
            <option value="node">{t("taskLinks.kindNode")}</option>
          </select>
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={kind === "work_package" ? t("taskLinks.workPackage") : t("taskLinks.node")}>
            <input
              value={externalId}
              onChange={(e) => setExternalId(e.target.value)}
              placeholder={kind === "work_package" ? "4711" : "n-8f2c"}
              aria-invalid={(id !== "" && !idValid) || undefined}
              className={`${INPUT} font-code`}
            />
          </Field>
          {kind === "node" && (
            <Field label={t("taskLinks.scope")}>
              <input
                value={scope}
                onChange={(e) => setScope(e.target.value)}
                placeholder="my-project"
                className={`${INPUT} font-code`}
              />
            </Field>
          )}
          <Field label={t("taskLinks.role")}>
            <select value={role} onChange={(e) => setRole(e.target.value as ExternalRefRole)} className={INPUT}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(ROLE_LABEL[r])}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("taskLinks.pinnedVersion")}>
            <input
              value={pinned}
              inputMode="numeric"
              onChange={(e) => setPinned(e.target.value.trim())}
              aria-invalid={!pinnedValid || undefined}
              className={`${INPUT} font-code`}
            />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-ui text-text-primary">
          <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} />
          {t("taskLinks.requiredLabel")}
        </label>
        {files.length > 0 && (
          <Field label={t("addRelation.file")}>
            <select value={path} onChange={(e) => setPath(e.target.value)} className={INPUT}>
              <option value="">{t("addRelation.wholeDocument")}</option>
              {files.map((f) => (
                <option key={f.path} value={f.path}>
                  {f.path}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label={t("taskLinks.label")}>
          <input value={label} maxLength={1000} onChange={(e) => setLabel(e.target.value)} className={INPUT} />
        </Field>
        <Field label={t("taskLinks.url")}>
          <input
            type="url"
            value={url}
            maxLength={2048}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://"
            className={INPUT}
          />
        </Field>
        <Field label={t("addRelation.note")}>
          <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} className={INPUT} />
        </Field>
        {id !== "" && !idValid && (
          <p className="text-meta text-danger">
            {kind === "work_package" ? t("taskLinks.workPackageInvalid") : t("taskLinks.nodeInvalid")}
          </p>
        )}
        {error && (
          <p role="alert" className="text-ui text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={!valid || busy}>
            {busy ? t("common.saving") : t("taskLinks.link")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
