import type { AppChange } from "../../api";
import { t, type MessageKey } from "../../lib/i18n";
import { ChangeMarker } from "../DiffFileMeta";

/**
 * What changed in a micro-application between two package versions, in the
 * app's terms, above the file diff of the comparison screen.
 */
export function AppChanges({ changes }: { changes: AppChange[] }) {
  return (
    <section aria-labelledby="app-changes" className="rounded-card border border-border bg-surface p-4">
      <h2 id="app-changes" className="text-ui font-medium mb-3">
        {t("appChanges.title")}
      </h2>
      {changes.length === 0 ? (
        <p className="text-meta text-text-secondary">{t("appChanges.none")}</p>
      ) : (
        <ul className="space-y-1">
          {changes.map((c) => (
            <li key={`${c.area}:${c.name}:${c.change}`} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-ui">
              <ChangeMarker change={c.change === "changed" ? "modified" : c.change} />
              <span className="text-text-secondary">{t(`appChanges.area.${c.area}` as MessageKey)}</span>
              <code className="font-code">{c.name}</code>
              <span className="text-meta text-text-tertiary">{t(`appChanges.change.${c.change}` as MessageKey)}</span>
              {c.detail && <span className="font-code text-meta text-text-secondary">{c.detail}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
