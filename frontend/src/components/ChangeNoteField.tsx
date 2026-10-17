import { clsx } from "clsx";
import { t } from "../lib/i18n";

/** Longest note the dialogs accept; a note is one or two sentences, like a commit message. */
const CHANGE_NOTE_MAX = 500;

/** Optional "what changed" note sent with a new version and shown in its history. */
export function ChangeNoteField({
  value,
  onChange,
  disabled = false,
  className,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <label className={clsx("block", className)}>
      <span className="mb-1.5 block text-ui font-medium text-text-primary">
        {t("changeNote.label")}
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={CHANGE_NOTE_MAX}
        disabled={disabled}
        placeholder={t("changeNote.placeholder")}
        className={clsx(
          "block w-full h-10 px-3 rounded-control",
          "bg-surface border border-border text-text-primary text-ui",
          "focus:border-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/35",
          "transition-[border-color,box-shadow] duration-150 ease-standard disabled:opacity-50",
        )}
      />
    </label>
  );
}

/** The note as the API takes it: trimmed, and omitted when empty. */
export function changeNoteParam(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}
