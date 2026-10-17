import { useMemo } from "react";
import { clsx } from "clsx";

import { estimatePasswordStrength } from "../lib/passwordStrength";

/** Colour per score, weakest first. */
const BAR_TONE = [
  "bg-[var(--color-danger)]",
  "bg-[var(--color-warning)]",
  "bg-[var(--color-info)]",
  "bg-[var(--color-success)]",
] as const;

const TEXT_TONE = [
  "text-[var(--color-danger)]",
  "text-[var(--color-warning)]",
  "text-[var(--color-info)]",
  "text-[var(--color-success)]",
] as const;

/**
 * Advisory strength meter. It reports, it never blocks - the only rule the
 * server enforces is the minimum length, and a simple password is a choice
 * the person is allowed to make.
 */
export function PasswordStrength({ password }: { password: string }) {
  const strength = useMemo(() => estimatePasswordStrength(password), [password]);

  if (password.length === 0) return null;

  return (
    <div className="mt-2" aria-live="polite">
      <div className="flex gap-1" role="presentation">
        {[0, 1, 2, 3].map((segment) => (
          <span
            key={segment}
            className={clsx(
              "h-1 flex-1 rounded-full transition-colors duration-150",
              segment <= strength.score ? BAR_TONE[strength.score] : "bg-border",
            )}
          />
        ))}
      </div>
      <p className="mt-1 text-meta text-text-tertiary">
        <span className={clsx("font-semibold", TEXT_TONE[strength.score])}>{strength.label}</span>
        {strength.hint ? `: ${strength.hint}` : null}
      </p>
    </div>
  );
}
