import { clsx } from "clsx";
import { t } from "../../lib/i18n";

import type { SimNode } from "./types";

export function HoverPanel({
  info,
  onOpen,
}: {
  info: { node: SimNode; neighbours: SimNode[] };
  onOpen: () => void;
}) {
  return (
    <div
      className={clsx(
        "absolute bottom-3 left-3 max-w-sm",
        "rounded-control border border-border bg-surface shadow-floating",
        "px-4 py-3 space-y-2 pointer-events-auto",
      )}
    >
      <div className="flex items-baseline justify-between gap-3">
        <button
          type="button"
          onClick={onOpen}
          className="font-medium text-text-primary hover:text-accent text-left truncate"
        >
          {info.node.title}
        </button>
        <span className="font-code tabular-nums text-meta text-text-tertiary shrink-0">
          {info.node.out_degree}→ · ←{info.node.in_degree}
        </span>
      </div>
      <code className="block font-code text-meta text-text-tertiary truncate">
        {info.node.path}
      </code>
      {info.neighbours.length > 0 && (
        <div className="pt-1 border-t border-border">
          <p className="text-meta text-text-secondary mb-1 font-medium">
            {t("vaultGraph.connections", { count: info.neighbours.length })}
          </p>
          <ul className="space-y-0.5 max-h-32 overflow-y-auto">
            {info.neighbours.slice(0, 8).map((n) => (
              <li key={n.path} className="text-ui text-text-secondary truncate">
                {n.title}
              </li>
            ))}
            {info.neighbours.length > 8 && (
              <li className="text-meta text-text-tertiary">
                {t("vaultGraph.andMore", { count: info.neighbours.length - 8 })}
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
