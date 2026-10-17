import { clsx } from "clsx";
import { t } from "../../lib/i18n";

import type { GraphSettings } from "./types";

export function SettingsPanel({
  settings,
  onChange,
  onReset,
  onClose,
}: {
  settings: GraphSettings;
  onChange: (s: GraphSettings) => void;
  onReset: () => void;
  onClose: () => void;
}) {
  const set = <K extends keyof GraphSettings>(k: K, v: GraphSettings[K]) =>
    onChange({ ...settings, [k]: v });
  return (
    <div
      className={clsx(
        "absolute top-14 right-3 w-72",
        "rounded-control border border-border bg-surface shadow-floating",
        "px-4 py-4 space-y-4",
      )}
    >
      <div className="flex items-baseline justify-between">
        <p className="text-meta text-text-secondary font-medium">
          {t("vaultGraph.settings")}
        </p>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("vaultGraph.closeSettings")}
          className="text-text-tertiary hover:text-text-primary font-code text-meta"
        >
          ×
        </button>
      </div>

      <Slider
        label={t("vaultGraph.repulsion")}
        min={300} max={5000} step={50}
        value={settings.repulsion}
        onChange={(v) => set("repulsion", v)}
        unit=""
      />
      <Slider
        label={t("vaultGraph.linkDistance")}
        min={40} max={600} step={10}
        value={settings.linkDistance}
        onChange={(v) => set("linkDistance", v)}
        unit="px"
      />
      <Slider
        label={t("vaultGraph.linkForce")}
        min={0.005} max={0.06} step={0.001} decimals={3}
        value={settings.linkForce}
        onChange={(v) => set("linkForce", v)}
        unit=""
      />
      <Slider
        label={t("vaultGraph.nodeScale")}
        min={0.5} max={3.0} step={0.1} decimals={1}
        value={settings.nodeScale}
        onChange={(v) => set("nodeScale", v)}
        unit="×"
      />
      <Slider
        label={t("vaultGraph.centerForce")}
        min={0.0001} max={0.01} step={0.0001} decimals={4}
        value={settings.centerForce}
        onChange={(v) => set("centerForce", v)}
        unit=""
      />

      <div>
        <p className="text-meta text-text-secondary mb-1.5 font-medium">
          {t("vaultGraph.labels")}
        </p>
        <div className="flex gap-0">
          {(["always", "hover", "off"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => set("labels", m)}
              className={clsx(
                "flex-1 py-1.5 text-meta transition-colors",
                "border-b-2 -mb-px",
                settings.labels === m
                  ? "border-accent text-text-primary font-medium"
                  : "border-transparent text-text-tertiary hover:text-text-secondary",
              )}
            >
              {m === "always"
                ? t("vaultGraph.labelsAlways")
                : m === "hover"
                  ? t("vaultGraph.labelsHover")
                  : t("vaultGraph.labelsOff")}
            </button>
          ))}
        </div>
      </div>

      <label className="flex items-center gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={settings.showArrows}
          onChange={(e) => set("showArrows", e.target.checked)}
          className="accent-accent"
        />
        <span className="text-ui text-text-primary">
          {t("vaultGraph.arrows")}
        </span>
      </label>

      <div className="flex justify-end pt-2 border-t border-border">
        <button
          type="button"
          onClick={onReset}
          className="text-meta text-text-tertiary hover:text-accent"
        >
          {t("vaultGraph.reset")}
        </button>
      </div>
    </div>
  );
}

function Slider({
  label,
  min,
  max,
  step,
  value,
  onChange,
  unit,
  decimals = 0,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (v: number) => void;
  unit: string;
  decimals?: number;
}) {
  return (
    <label className="block">
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-meta text-text-secondary font-medium">
          {label}
        </span>
        <span className="font-code tabular-nums text-meta text-text-secondary">
          {value.toFixed(decimals)}
          {unit && <span className="text-text-tertiary"> {unit}</span>}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-accent"
      />
    </label>
  );
}
