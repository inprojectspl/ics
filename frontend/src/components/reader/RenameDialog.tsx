import { useState, type FormEvent } from "react";
import { t } from "../../lib/i18n";
import { Field, INPUT_CLASS } from "../Field";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

interface Props {
  title: string;
  onRename: (next: string) => Promise<void>;
  onClose: () => void;
}

/** Rename the open document: its own action, never a click on the title. */
export function RenameDialog({ title, onRename, onClose }: Props) {
  const [draft, setDraft] = useState(title);
  const [busy, setBusy] = useState(false);
  const next = draft.trim();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!next || next === title) return onClose();
    setBusy(true);
    await onRename(next);
    setBusy(false);
  };

  return (
    <Dialog title={t("assetMenu.rename")} onClose={onClose} maxWidth="lg">
      <form onSubmit={submit} className="space-y-4 px-5 py-5 sm:px-6">
        <Field label={t("assetToolbar.nameLabel")}>
          <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={255} className={INPUT_CLASS} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" busy={busy} disabled={!next}>
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
