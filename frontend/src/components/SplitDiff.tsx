import { clsx } from "clsx";
import { t } from "../lib/i18n";
import type { Segment } from "../lib/intralineDiff";
import type { SplitRow } from "../lib/parseUnifiedDiff";
import { IntralineText } from "./IntralineText";

interface Props {
  /** Rows from `pairForSplit`. `DiffFileBlock` computes parsing and highlights
   * once, so switching modes recomputes nothing. */
  rows: SplitRow[];
}

/**
 * Side-by-side view: old version on the left, new on the right, with line
 * numbers. Alternative to `UnifiedDiff` (stacked); the mode is picked in the
 * comparison screen sidebar.
 */
export function SplitDiff({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <p className="text-meta text-text-tertiary py-6">
        {t("diffView.identical")}
      </p>
    );
  }

  return (
    <div className="rounded-control border border-border bg-code-bg overflow-x-auto">
      <table className="w-full border-collapse font-code text-meta leading-relaxed">
        <caption className="sr-only">
          {t("splitDiff.caption")}
        </caption>
        <tbody>
          {rows.map((row, i) => (
            <Row key={i} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Row({ row }: { row: SplitRow }) {
  if (row.kind === "hunk") {
    return (
      <tr className="bg-accent-soft/30 text-accent">
        <td colSpan={4} className="px-4 py-0.5">
          {row.header}
        </td>
      </tr>
    );
  }
  const removed = row.kind === "change" || row.kind === "remove";
  const added = row.kind === "change" || row.kind === "add";
  return (
    <tr>
      <Gutter n={row.leftNo} />
      <Side
        text={row.left}
        segments={row.leftSegments}
        tone={removed ? "removed" : "context"}
        sign={removed ? "-" : " "}
      />
      <Gutter n={row.rightNo} />
      <Side
        text={row.right}
        segments={row.rightSegments}
        tone={added ? "added" : "context"}
        sign={added ? "+" : " "}
      />
    </tr>
  );
}

function Gutter({ n }: { n: number | null }) {
  return (
    <td className="w-10 select-none px-2 text-right align-top text-text-tertiary/70 tabular-nums">
      {n ?? ""}
    </td>
  );
}

function Side({
  text,
  segments,
  tone,
  sign,
}: {
  text: string | null;
  segments?: Segment[];
  tone: "added" | "removed" | "context";
  sign: string;
}) {
  return (
    <td
      className={clsx(
        "w-1/2 whitespace-pre-wrap break-words px-2 align-top",
        tone === "added" && "bg-success/10 text-success",
        tone === "removed" && "bg-danger/10 text-danger",
        tone === "context" && "text-text-secondary",
        // Empty cell on the side without a line, shown as a visible gap so the
        // eye does not pair unrelated lines.
        text === null && "bg-surface-subtle/40",
      )}
    >
      {text === null ? (
        ""
      ) : (
        <>
          {sign} <IntralineText text={text} segments={segments} tone={tone} />
        </>
      )}
    </td>
  );
}
