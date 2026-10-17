import type { InputHTMLAttributes } from "react";
import { clsx } from "clsx";
import { Loader2, Search, X } from "lucide-react";
import { t } from "../lib/i18n";
import { INPUT_CLASS } from "./Field";

interface Props {
  value: string;
  onChange: (v: string) => void;
  /** A server search is in flight. */
  busy?: boolean;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
  /** Extra attributes of the input, e.g. the combobox role and its ARIA state. */
  inputProps?: Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type" | "className">;
}

/** The search field of every list: icon, clear button, busy indicator. */
export function SearchInput({
  value,
  onChange,
  busy = false,
  placeholder = t("searchInput.placeholder"),
  ariaLabel = t("searchInput.label"),
  className,
  inputProps,
}: Props) {
  return (
    <div className={clsx("relative", className)}>
      <Search size={16} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
      <input
        {...inputProps}
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          inputProps?.onKeyDown?.(e);
          if (e.key === "Escape" && value && !e.defaultPrevented) {
            e.stopPropagation();
            onChange("");
          }
        }}
        placeholder={placeholder}
        aria-label={ariaLabel}
        className={clsx(INPUT_CLASS, "pl-9 pr-9 shadow-card [&::-webkit-search-cancel-button]:hidden")}
      />
      <span className="absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center">
        {busy ? (
          <Loader2 size={16} aria-label={t("palette.searching")} className="mr-1 animate-spin text-text-secondary" />
        ) : value ? (
          <button
            type="button"
            onClick={() => onChange("")}
            aria-label={t("searchInput.clear")}
            className="inline-flex size-7 items-center justify-center rounded-control text-text-secondary hover:bg-surface-hover hover:text-text-primary"
          >
            <X size={14} aria-hidden />
          </button>
        ) : null}
      </span>
    </div>
  );
}
