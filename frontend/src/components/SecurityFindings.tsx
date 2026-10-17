import { useMemo, useState } from "react";
import { clsx } from "clsx";
import { FileCode2, FolderOpen } from "lucide-react";
import { SecurityReport, SecurityStatus } from "../api";
import { t, tn, type MessageKey, type PluralKey } from "../lib/i18n";
import { Badge, type BadgeTone } from "./ui/Badge";

type Finding = SecurityReport["findings"][number];
type Severity = Finding["severity"];

/** Most severe first: the order of groups, badges and counts. */
export const SEVERITIES: readonly Severity[] = ["critical", "warn", "info"];

/** How each severity is shown: badge tone, its name, and the count on a queued bundle. */
export const SEVERITY: Record<Severity, { tone: BadgeTone; label: MessageKey; count: PluralKey }> = {
  critical: { tone: "danger", label: "securityFindings.severity.critical", count: "adminReview.criticalCount" },
  warn: { tone: "warning", label: "securityFindings.severity.warn", count: "adminReview.warnCount" },
  info: { tone: "neutral", label: "securityFindings.severity.info", count: "adminReview.infoCount" },
};

const rank = (s: Severity) => SEVERITIES.indexOf(s);

interface RuleGroup {
  rule: string;
  severity: Severity;
  message: string;
  places: { file: string; line: number | null }[];
}

/** One group per rule, the most severe first; places in path and line order. */
export function groupFindings(findings: readonly Finding[]): RuleGroup[] {
  const byRule = new Map<string, RuleGroup>();
  for (const f of findings) {
    const key = `${f.severity}:${f.rule}`;
    const g = byRule.get(key) ?? { rule: f.rule, severity: f.severity, message: f.message, places: [] };
    g.places.push({ file: f.file, line: f.line });
    byRule.set(key, g);
  }
  const groups = [...byRule.values()];
  for (const g of groups) g.places.sort((a, b) => a.file.localeCompare(b.file) || (a.line ?? 0) - (b.line ?? 0));
  return groups.sort((a, b) => rank(a.severity) - rank(b.severity) || b.places.length - a.places.length);
}

/** The first `cap` places across the groups, each group keeping its full count. */
function capPlaces(groups: RuleGroup[], cap: number) {
  const out: (RuleGroup & { total: number })[] = [];
  let left = cap;
  for (const g of groups) {
    if (left <= 0) break;
    const places = g.places.slice(0, left);
    left -= places.length;
    out.push({ ...g, places, total: g.places.length });
  }
  return out;
}

/** Folder every finding sits in (`dist/`), said once instead of on each path. */
export function commonFolder(findings: readonly Finding[]): string {
  const first = findings[0]?.file ?? "";
  let prefix = first.slice(0, first.lastIndexOf("/") + 1);
  for (const f of findings) {
    while (prefix && !f.file.startsWith(prefix)) prefix = prefix.slice(0, prefix.lastIndexOf("/", prefix.length - 2) + 1);
  }
  return prefix;
}

/** Counts per severity, for the badges of a queued bundle. */
export function severityCounts(findings: readonly Finding[]): Record<Severity, number> {
  const out: Record<Severity, number> = { critical: 0, warn: 0, info: 0 };
  for (const f of findings) out[f.severity]++;
  return out;
}


/**
 * Everything the scanner found, one entry per problem with every place it
 * occurs (full path and line), so the reader sees what is wrong and where
 * without paths cut short. `limit` caps the places shown until asked.
 */
export function FindingsList({ findings, limit }: { findings: readonly Finding[]; limit?: number }) {
  const [all, setAll] = useState(false);
  const groups = useMemo(() => groupFindings(findings), [findings]);
  const folder = useMemo(() => commonFolder(findings), [findings]);
  const cap = all || limit === undefined ? Infinity : limit;
  const visible = useMemo(() => capPlaces(groups, cap), [groups, cap]);
  const shown = visible.reduce((n, g) => n + g.places.length, 0);

  return (
    <div className="space-y-3">
      {folder && (
        <p className="flex items-start gap-2 text-meta text-text-secondary">
          <FolderOpen size={16} aria-hidden className="mt-px shrink-0" />
          <span className="min-w-0">
            {t("securityFindings.inFolder")} <code className="break-all font-code text-text-primary">{folder}</code>
          </span>
        </p>
      )}
      {visible.map((g) => {
        return (
          <section key={`${g.severity}:${g.rule}`} className="overflow-hidden rounded-control border border-border bg-surface">
            <header className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border px-3 py-2">
              <Badge tone={SEVERITY[g.severity].tone}>{t(SEVERITY[g.severity].label)}</Badge>
              <h4 className="min-w-0 flex-1 text-ui font-medium text-text-primary">{g.message}</h4>
              <span className="text-meta tabular-nums text-text-secondary">{tn("securityFindings.places", g.total)}</span>
            </header>
            <ul className="px-3 py-1.5">
              {g.places.map((p, i) => (
                <li key={`${p.file}:${p.line}:${i}`} className="flex items-start gap-2 py-1">
                  <FileCode2 size={14} aria-hidden className="mt-0.5 shrink-0 text-text-tertiary" />
                  <code className="min-w-0 break-all font-code text-meta text-text-primary">
                    {p.file.slice(folder.length)}
                    <span className="text-text-secondary">
                      {p.line == null ? ` (${t("securityFindings.wholeFile")})` : `:${p.line}`}
                    </span>
                  </code>
                </li>
              ))}
            </ul>
            <p className="border-t border-border px-3 py-1.5 font-code text-meta text-text-tertiary">{g.rule}</p>
          </section>
        );
      })}
      {shown < findings.length && (
        <button type="button" onClick={() => setAll(true)} className="text-ui font-medium text-accent hover:underline">
          {t("securityFindings.showAll", { count: findings.length })}
        </button>
      )}
    </div>
  );
}

interface Props {
  status: SecurityStatus | null | undefined;
  report: SecurityReport | null | undefined;
  /** Bypass granted (manually or automatically): the banner stays hidden. */
  bypassed?: boolean;
}

/**
 * Findings banner on the document's landing card. Hidden when clean and
 * after a bypass, when there is no decision left for the owner; the report
 * stays on the asset and in the admin queue.
 */
export function SecurityFindings({ status, report, bypassed }: Props) {
  if (!status || status === "clean" || bypassed || !report || report.findings.length === 0) {
    return null;
  }
  const isCritical = status === "critical";
  return (
    <section
      className={clsx(
        "mb-8 rounded-card border px-4 py-4 sm:px-5",
        isCritical ? "border-danger/30 bg-danger-soft" : "border-warning/30 bg-warning-soft",
      )}
      role="alert"
    >
      <header className="mb-2 flex flex-wrap items-baseline gap-x-3">
        <span className={clsx("text-ui font-semibold", isCritical ? "text-danger" : "text-warning")}>
          {isCritical ? t("securityFindings.criticalHeading") : t("securityFindings.warnHeading")}
        </span>
        <span className="text-meta text-text-secondary">{tn("securityFindings.count", report.findings.length)}</span>
      </header>
      <p className="mb-4 text-ui text-text-secondary">
        {isCritical ? t("securityFindings.criticalBody") : t("securityFindings.warnBody")}
      </p>
      <FindingsList findings={report.findings} limit={12} />
    </section>
  );
}
