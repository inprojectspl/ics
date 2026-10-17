import type { ReactNode } from "react";
import { clsx } from "clsx";
import { t } from "../lib/i18n";
import { BackgroundGraph } from "./backgroundGraph/BackgroundGraph";
import { BrandMark } from "./BrandMark";
import { BuiltBy } from "./BuiltBy";
import { inputClass } from "./Field";
import { Button } from "./ui/Button";

/**
 * Screens without the signed-in shell (sign-in, reset, setup, link gates):
 * one calm card on the canvas. Standalone it carries the brand as the way
 * home over the drifting node backdrop; `bare` sits inside the public
 * shell, which already shows it.
 */
export function CenteredCard({ children, bare = false }: { children: ReactNode; bare?: boolean }) {
  const card = (
    <div className="w-full max-w-sm rounded-overlay border border-border bg-surface p-6 shadow-card sm:p-8">{children}</div>
  );
  if (bare) return <div className="flex flex-1 items-start justify-center px-4 py-12 sm:items-center">{card}</div>;
  return (
    <div className="relative isolate flex min-h-dvh flex-col items-center bg-canvas px-4">
      <BackgroundGraph />
      <div className="relative flex w-full flex-1 flex-col items-center justify-center py-12">
        <a href="/" aria-label={t("chrome.home")} className="mb-8 rounded-control p-1 text-text-primary">
          <BrandMark size={28} />
        </a>
        <div className="flex w-full justify-center">{card}</div>
      </div>
      <footer className="relative pb-6">
        <BuiltBy variant="page" />
      </footer>
    </div>
  );
}

/** Heading block of a `CenteredCard`: what this screen is for, in one line each. */
export function CardHeading({ title, lead }: { title: ReactNode; lead?: ReactNode }) {
  return (
    <div className="mb-6 text-center">
      <h1 className="text-title font-semibold text-text-primary [overflow-wrap:anywhere]">{title}</h1>
      {lead && <p className="mt-1.5 text-ui text-text-secondary">{lead}</p>}
    </div>
  );
}

interface FieldProps {
  label: string;
  type: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
  minLength?: number;
  required?: boolean;
}

export function Field({ label, type, value, onChange, autoComplete, minLength, required = true }: FieldProps) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-ui font-medium text-text-primary">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        minLength={minLength}
        required={required}
        className={inputClass({ size: "lg" })}
      />
    </label>
  );
}

/** The submit of a form screen: full width, 44 px, spinner while `busy`. */
export function PrimaryButton({
  className,
  ...rest
}: React.ComponentProps<typeof Button>) {
  return <Button size="lg" className={clsx("w-full", className)} {...rest} />;
}
