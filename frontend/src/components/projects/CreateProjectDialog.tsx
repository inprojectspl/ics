import { useState, type FormEvent } from "react";
import { api } from "../../api";
import { formatApiError } from "../../lib/apiError";
import { t } from "../../lib/i18n";
import { navigate } from "../../lib/navigate";
import { Field, INPUT_CLASS, TEXTAREA_CLASS } from "../Field";
import { useToast } from "../Toast";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

interface Props {
  onClose: () => void;
  onCreated: () => void;
}

/** New project: a name, optionally what it is for; then straight into it. */
export function CreateProjectDialog({ onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const p = await api.createProject(name.trim(), description.trim() || undefined);
      toast(t("projects.created"), "success");
      onCreated();
      onClose();
      navigate(`/projects/${p.slug}`);
    } catch (err) {
      setError(formatApiError(err, t("projects.createFailed")));
      setBusy(false);
    }
  };

  return (
    <Dialog title={t("projects.newProject")} onClose={onClose} maxWidth="lg">
      <form onSubmit={submit} className="space-y-4 px-5 py-5 sm:px-6">
        <Field label={t("common.name")}>
          <input
            autoFocus
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={255}
            className={INPUT_CLASS}
          />
        </Field>
        <Field label={t("projects.descriptionOptional")} hint={t("projects.descriptionHint")}>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            maxLength={4000}
            className={TEXTAREA_CLASS}
          />
        </Field>
        {error && (
          <p role="alert" className="text-ui text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" busy={busy} disabled={!name.trim()}>
            {t("common.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
