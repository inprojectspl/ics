import { clsx } from "clsx";
import type { Segment } from "../lib/intralineDiff";

interface Props {
  text: string;
  /** When given, fragments that differ from the paired line get a stronger
   * background (as in GitLab). Absent means the plain line background. */
  segments?: Segment[];
  tone: "added" | "removed" | "context";
}

/**
 * Text of a single diff line with changed fragments highlighted. Shared by
 * both view modes so a line looks the same in the split and stacked views.
 */
export function IntralineText({ text, segments, tone }: Props) {
  if (!segments) return <>{text}</>;
  const hl = tone === "added" ? "bg-success/25 rounded-[2px]" : "bg-danger/25 rounded-[2px]";
  return (
    <>
      {segments.map((seg, i) => (
        <span key={i} className={clsx(seg.changed && hl)}>
          {seg.text}
        </span>
      ))}
    </>
  );
}
