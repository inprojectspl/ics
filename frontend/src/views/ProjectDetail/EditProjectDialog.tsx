import { useState, type FormEvent } from "react";
import { t } from "../../lib/i18n";
import { Field, INPUT_CLASS, TEXTAREA_CLASS } from "../../components/Field";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";

interface Props {
  name: string;
  description: string | null;
  busy: boolean;
  /** Throws on failure: the dialog stays open with what was typed. */
  onSave: (name: string, description: string | null) => Promise<void>;
  onClose: () => void;
}

/** Rename a project and say what it is for. Blank names are blocked here
 * as they are by the API. */
export function EditProjectDialog({ name, description, busy, onSave, onClose }: Props) {
  const [nameDraft, setName] = useState(name);
  const [descDraft, setDesc] = useState(description ?? "");
  const trimmed = nameDraft.trim();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!trimmed) return;
    try {
      await onSave(trimmed, descDraft.trim() || null);
      onClose();
    } catch {
      // The toast told why; keep the draft for another try.
    }
  };

  return (
    <Dialog title={t("projectHeader.editTitle")} onClose={onClose} maxWidth="lg">
      <form onSubmit={submit} className="space-y-4 px-5 py-5 sm:px-6">
        <Field label={t("projectHeader.nameLabel")}>
          <input autoFocus required maxLength={255} value={nameDraft} onChange={(e) => setName(e.target.value)} className={INPUT_CLASS} />
        </Field>
        <Field label={t("projects.descriptionOptional")} hint={t("projects.descriptionHint")}>
          <textarea rows={4} maxLength={4000} value={descDraft} onChange={(e) => setDesc(e.target.value)} className={TEXTAREA_CLASS} />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" busy={busy} disabled={!trimmed}>
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
