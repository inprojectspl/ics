import type { AgentView } from "../api";
import { formatBytes } from "../lib/format";
import { formatNumber, t, tn } from "../lib/i18n";
import { Button } from "./ui/Button";

interface Props {
  view: AgentView;
  /** The `ics_asset_read` call that returns `view.content`. */
  call: string;
  copy: (text: string, key?: string) => Promise<void>;
  copiedKey: string | null;
}

/** What the agent pays for the file: size, the MCP call and how many reads
 * cover it, shown above the content of the agent view. */
export function AgentViewStats({ view, call, copy, copiedKey }: Props) {
  const facts = [
    tn("agentView.lineCount", view.total_lines),
    formatBytes(view.size_bytes),
    tn("agentView.tokenCount", view.estimated_tokens),
    view.page_count !== undefined ? tn("agentView.pageCount", view.page_count) : null,
    view.version !== view.current_version
      ? t("agentView.archived", { version: view.version })
      : null,
  ].filter((f): f is string => f !== null);

  return (
    <div className="mb-4 space-y-2 text-meta text-text-tertiary">
      <p className="flex flex-wrap gap-x-2 gap-y-1">
        {facts.map((f, i) => (
          <span key={f} className="tabular-nums">
            {i > 0 && <span className="text-text-tertiary/50 mr-2">·</span>}
            {f}
          </span>
        ))}
      </p>
      <div className="flex flex-wrap items-start gap-x-2 gap-y-1 min-w-0">
        <span className="w-full sm:w-auto shrink-0 pt-0.5">{t("agentView.call")}</span>
        <code className="min-w-0 flex-1 break-all rounded-control bg-surface-subtle px-2 py-0.5 font-code text-ui text-text-secondary">
          {call}
        </code>
        <Button variant="ghost" size="sm" onClick={() => void copy(call, "call")}>
          {copiedKey === "call" ? t("agentView.copied") : t("agentView.copyCall")}
        </Button>
      </div>
      {view.agent_reads > 1 && (
        <p>
          {t("agentView.paged", {
            count: formatNumber(view.agent_reads),
            lines: formatNumber(view.lines_per_read),
          })}
        </p>
      )}
      {view.truncated && (
        <p className="text-warning">
          {t("agentView.truncated", {
            shown: formatNumber(view.shown_lines),
            total: formatNumber(view.total_lines),
          })}
        </p>
      )}
    </div>
  );
}
