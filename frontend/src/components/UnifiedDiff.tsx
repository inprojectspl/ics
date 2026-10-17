import { clsx } from "clsx";
import { t } from "../lib/i18n";
import type { DiffLine } from "../lib/parseUnifiedDiff";
import { IntralineText } from "./IntralineText";

interface Props {
  /** Lines from `parseUnifiedDiff` + `annotateIntraline`, computed once by
   * `DiffFileBlock` so switching modes does not re-parse. */
  lines: DiffLine[];
}

/**
 * Unified mode: lines stacked in unified diff order, with changed
 * fragments highlighted within each line.
 */
export function UnifiedDiff({ lines }: Props) {
  if (lines.length === 0) {
    return (
      <p className="text-meta text-text-tertiary py-6">
        {t("diffView.identical")}
      </p>
    );
  }
  return (
    <pre
      className={clsx(
        "rounded-control border border-border bg-code-bg",
        "font-code text-meta leading-relaxed",
      )}
    >
      <code>
        {lines.map((line, i) => (
          // Long lines wrap; the sign sits in its own column so continuation
          // rows stay aligned with the text, not under the +/-.
          <span
            key={i}
            className={clsx("grid grid-cols-[1ch_minmax(0,1fr)] whitespace-pre-wrap px-4 [overflow-wrap:anywhere]", toneCls(line.kind))}
          >
            {line.kind === "hunk" ? (
              <span className="col-span-2">{line.header}</span>
            ) : (
              <>
                <span>{SIGN[line.kind]}</span>
                <span>
                  <IntralineText
                    text={line.text}
                    segments={line.segments}
                    tone={line.kind === "add" ? "added" : "removed"}
                  />
                </span>
              </>
            )}
          </span>
        ))}
      </code>
    </pre>
  );
}

const SIGN = { context: " ", add: "+", remove: "-" } as const;

function toneCls(kind: DiffLine["kind"]): string {
  switch (kind) {
    case "hunk":
      return "text-accent bg-accent-soft/30";
    case "add":
      return "text-success bg-success/10";
    case "remove":
      return "text-danger bg-danger/10";
    case "context":
      return "text-text-secondary";
  }
}
