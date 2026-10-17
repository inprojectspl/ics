import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { api } from "../api";
import { formatApiError } from "../lib/apiError";
import { t } from "../lib/i18n";
import { ChangeNoteField, changeNoteParam } from "./ChangeNoteField";
import { useConfirm } from "./ConfirmDialog";
import { TEXTAREA_CLASS } from "./Field";
import { Button } from "./ui/Button";

interface Props {
  assetId: string;
  slug: string;
  /** For md_collection: the file currently in view. For md_single: undefined. */
  path?: string;
  /** Called after a successful save so the parent can re-fetch the doc. */
  onSaved: (newVersion: number) => void;
  onCancel: () => void;
}

/**
 * Plain monospace textarea with a sticky save bar. No CodeMirror/Monaco on
 * purpose: they are 100kb+ for what is a "fix a typo" editor.
 * Esc cancels (confirming if dirty), Ctrl/Cmd+Enter saves.
 */
export function InlineEditor({ assetId, slug, path, onSaved, onCancel }: Props) {
  const [original, setOriginal] = useState<string | null>(null);
  const [draft, setDraft] = useState<string>("");
  const [changeNote, setChangeNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"loading" | "saving" | null>("loading");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const confirm = useConfirm();

  useEffect(() => {
    let cancelled = false;
    api
      .getSource(slug, path)
      .then((r) => {
        if (cancelled) return;
        setOriginal(r.content);
        setDraft(r.content);
        setBusy(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(formatApiError(e));
        setBusy(null);
      });
    return () => {
      cancelled = true;
    };
  }, [slug, path]);

  const dirty = original !== null && draft !== original;

  const tryCancel = async () => {
    if (dirty) {
      const ok = await confirm({
        title: t("inlineEditor.discardTitle"),
        message: t("inlineEditor.discardMessage"),
        confirmLabel: t("inlineEditor.discard"),
        destructive: true,
      });
      if (!ok) return;
    }
    onCancel();
  };

  const save = async () => {
    if (!dirty || busy) return;
    setBusy("saving");
    setError(null);
    try {
      const r = await api.editContent(assetId, draft, path, changeNoteParam(changeNote));
      onSaved(r.version);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        void tryCancel();
      } else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // save and tryCancel read only dirty, draft and busy, so rebinding on
    // those keeps the handlers current without a listener per render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, draft, busy, changeNote]);

  return (
    <article className="w-full max-w-(--reading-width) mx-auto px-(--gutter) py-10">
      <header className="flex items-baseline justify-between mb-4 gap-4">
        <div>
          <p className="text-meta text-text-secondary mb-1 font-medium">
            {t("inlineEditor.heading")}
          </p>
          {path && (
            <code className="font-code text-meta text-text-secondary">{path}</code>
          )}
        </div>
        <span className="text-meta text-text-tertiary">
          {t("inlineEditor.shortcuts")}
        </span>
      </header>

      {busy === "loading" && (
        <p className="text-text-tertiary text-meta py-12 text-center">{t("inlineEditor.loading")}</p>
      )}

      {original !== null && (
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          spellCheck={false}
          className={clsx(TEXTAREA_CLASS, "min-h-[60vh] resize-y px-5 py-4 font-code")}
        />
      )}

      {original !== null && (
        <ChangeNoteField
          value={changeNote}
          onChange={setChangeNote}
          disabled={busy === "saving"}
          className="mt-4"
        />
      )}

      {error && <p className="text-ui text-danger mt-3">{error}</p>}

      <div
        className={clsx(
          "sticky bottom-0 -mx-(--gutter) px-(--gutter) py-3 mt-4",
          "bg-surface/95 backdrop-blur-md border-t border-border",
          "flex items-center justify-end gap-3",
        )}
      >
        <span className="text-meta text-text-tertiary mr-auto">
          {dirty ? t("inlineEditor.unsaved") : t("inlineEditor.noChanges")}
        </span>
        <Button variant="ghost" onClick={tryCancel} disabled={busy === "saving"}>
          {t("common.cancel")}
        </Button>
        <Button onClick={save} busy={busy === "saving"} disabled={!dirty || busy !== null}>
          {busy === "saving" ? t("common.saving") : t("inlineEditor.save")}
        </Button>
      </div>
    </article>
  );
}
