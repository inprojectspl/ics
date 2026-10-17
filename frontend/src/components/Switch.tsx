import { useId, type ReactNode } from "react";
import { clsx } from "clsx";

interface Props {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}

/** On/off setting: a labelled `role="switch"` button with an optional
 * description under the label. */
export function Switch({ checked, onChange, label, description, disabled = false }: Props) {
  const labelId = useId();
  const descId = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <p id={labelId} className="text-ui font-medium text-text-primary">
          {label}
        </p>
        {description && (
          <p id={descId} className="text-meta text-text-tertiary mt-0.5">
            {description}
          </p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        aria-describedby={description ? descId : undefined}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={clsx(
          "relative shrink-0 inline-flex items-center w-11 h-6 rounded-full transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
          "disabled:opacity-50",
          checked ? "bg-accent" : "bg-border",
        )}
      >
        <span
          aria-hidden
          className={clsx(
            "absolute left-0.5 size-5 rounded-full bg-surface shadow-card transition-transform",
            checked && "translate-x-5",
          )}
        />
      </button>
    </div>
  );
}
