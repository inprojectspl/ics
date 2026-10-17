import { FormEvent, useState } from "react";
import { clsx } from "clsx";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { Button } from "./ui/Button";
import { Dialog } from "./ui/Dialog";
import { INPUT_CLASS } from "./Field";

interface Props {
  /** Existing paths in the vault - used to warn about conflicts before
   * the request goes out. The backend repeats the check (409). */
  existing: string[];
  /** Pre-fills the path input with `${defaultFolder}/`, so typing just a
   * name lands inside that folder. */
  defaultFolder?: string;
  onClose: () => void;
  /** Called with the user-provided path (normalised) when the user
   * submits. Caller posts to the API and re-fetches the tree. */
  onCreate: (path: string) => Promise<void>;
}

/** Creates an empty `.md` in a vault from a typed path (e.g. `notes/idea.md`). */
export function NewFileDialog({ existing, defaultFolder = "", onClose, onCreate }: Props) {
  const [path, setPath] = useState(defaultFolder ? `${defaultFolder}/` : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const normalised = normalisePath(path);
  const conflict = normalised && existing.includes(normalised);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!normalised) {
      setError(t("newFile.pathRequired"));
      return;
    }
    if (!normalised.toLowerCase().endsWith(".md")) {
      setError(t("newFile.mdRequired"));
      return;
    }
    if (conflict) {
      setError(t("newFile.exists", { path: normalised }));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onCreate(normalised);
    } catch (e) {
      setError(formatApiError(e));
      setBusy(false);
    }
  };

  return (
    <Dialog title={t("newFile.title")} onClose={onClose} maxWidth="md">
      <form onSubmit={onSubmit} className="px-6 py-5 space-y-4">
        <label className="block">
          <span className="mb-1.5 block text-ui font-medium text-text-primary">
            {t("newFile.pathLabel")}
          </span>
          <input
            autoFocus
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="notes/idea.md"
            className={clsx(INPUT_CLASS, "font-code")}
          />
        </label>
        <p className="text-meta text-text-tertiary leading-relaxed">
          {t("newFile.hintBefore")} (<code>notes/2026/idea.md</code>).{" "}
          {t("newFile.hintAfter")}
        </p>

        {error && <p className="text-ui text-danger">{error}</p>}
        {!error && conflict && (
          <p className="text-ui text-warning">
            {t("newFile.conflictWarning")}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" busy={busy} disabled={!normalised || Boolean(conflict)}>
            {busy ? t("common.creating") : t("common.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** Strip a leading slash, collapse repeats, drop "." and ".." segments
 * client-side. The backend repeats this in `normalize_collection_path`
 * - we only echo it for the UI hint and conflict detection. */
function normalisePath(raw: string): string {
  const parts = raw
    .trim()
    .replace(/^\/+|\/+$/g, "")
    .split("/")
    .map((p) => p.trim())
    .filter((p) => p && p !== "." && p !== "..");
  return parts.join("/");
}
