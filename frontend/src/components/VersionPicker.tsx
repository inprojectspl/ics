import { clsx } from "clsx";
import type { VersionRow } from "../api";
import { formatDateTime } from "../lib/format";
import { t } from "../lib/i18n";
import { inputClass } from "./Field";

interface Props {
  versions: VersionRow[];
  fromV: number;
  toV: number;
  onChange: (next: { fromV: number; toV: number }) => void;
  /** Extra content on the right (e.g. an "open full screen" link). */
  aside?: React.ReactNode;
}

/**
 * A from/to select pair for comparing versions, with author and date on each
 * option: with several editors, "v1 -> v2" alone does not say whose changes
 * they are. Shared by the versions modal and the comparison screen.
 */
export function VersionPicker({ versions, fromV, toV, onChange, aside }: Props) {
  const sorted = [...versions].sort((a, b) => a.version - b.version);
  return (
    <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-end gap-3 sm:gap-4">
      <VersionSelect
        label={t("versionPicker.from")}
        value={fromV}
        versions={sorted}
        disabled={toV}
        onChange={(v) => onChange({ fromV: v, toV })}
      />
      <span className="hidden sm:inline text-text-tertiary pb-2" aria-hidden>
        →
      </span>
      <VersionSelect
        label={t("versionPicker.to")}
        value={toV}
        versions={sorted}
        disabled={fromV}
        onChange={(v) => onChange({ fromV, toV: v })}
      />
      {aside && <div className="sm:pb-2 sm:ml-auto">{aside}</div>}
    </div>
  );
}

function VersionSelect({
  label,
  value,
  onChange,
  versions,
  disabled,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  versions: VersionRow[];
  /** Version picked on the other side; it is disabled because "v1 -> v1" is
   * the only way to produce the "versions must differ" error. */
  disabled?: number;
}) {
  return (
    <label className="flex flex-col gap-1 min-w-0">
      <span className="text-meta text-text-secondary font-medium">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className={clsx(inputClass({ full: false }), "w-full max-w-full sm:w-auto")}
      >
        {versions.map((v) => (
          <option key={v.version} value={v.version} disabled={v.version === disabled}>
            {optionLabel(v)}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Formats "v2 (current) · <date>, <time> · Jane Doe" with the author last,
 * because the list is narrow and the number and date are read first. */
function optionLabel(v: VersionRow): string {
  const parts = [
    v.is_current ? t("versionPicker.current", { version: v.version }) : `v${v.version}`,
  ];
  const when = formatDateTime(v.created_at);
  if (when) parts.push(when);
  if (v.author) parts.push(v.author);
  return parts.join(" · ");
}
