import type { DiffFileChange } from "../api";
import { t, type MessageKey } from "../lib/i18n";
import { ChangeMarker, DiffCounters } from "./DiffFileMeta";

interface Props {
  files: DiffFileChange[];
}

const GROUPS: Array<{ change: DiffFileChange["change"]; heading: MessageKey }> = [
  { change: "modified", heading: "versionDiffSummary.modified" },
  { change: "added", heading: "versionDiffSummary.added" },
  { change: "removed", heading: "versionDiffSummary.removed" },
];

/**
 * Changed files and line counts between versions, for every asset kind.
 * File contents are shown only on the full comparison screen
 * (`views/VersionDiff`), so the diff body has a single implementation.
 */
export function VersionDiffSummary({ files }: Props) {
  if (files.length === 0) {
    return (
      <p className="text-meta text-text-tertiary py-6">
        {t("versionDiffSummary.none")}
      </p>
    );
  }
  return (
    <div className="space-y-5">
      {GROUPS.map(({ change, heading }) => {
        const group = files.filter((f) => f.change === change);
        if (group.length === 0) return null;
        return (
          <section key={change}>
            <h4 className="text-meta text-text-secondary mb-2 font-medium">
              {t(heading)} <span className="font-code tabular-nums">{group.length}</span>
            </h4>
            <ul className="space-y-0.5">
              {group.map((f) => (
                <li key={f.path} className="flex items-baseline gap-2 py-1">
                  <ChangeMarker change={f.change} />
                  <span className="font-code text-ui text-text-secondary truncate">{f.path}</span>
                  <DiffCounters file={f} />
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
