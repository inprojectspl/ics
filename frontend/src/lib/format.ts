import type { AssetKind } from "../api";
import { formatNumber, intlLocale, t, tn } from "./i18n";

function oneDecimal(n: number): string {
  return formatNumber(n, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${oneDecimal(n / 1024)} KB`;
  return `${oneDecimal(n / 1024 / 1024)} MB`;
}

export function kindLabel(kind: AssetKind): string {
  switch (kind) {
    case "md_single": return t("kind.mdSingle");
    case "md_collection": return t("kind.mdCollection");
    case "html_bundle": return t("kind.htmlBundle");
    case "pdf_doc": return t("kind.pdfDoc");
    case "office_doc": return t("kind.officeDoc");
  }
}

export function versionCountLabel(n: number): string {
  return tn("format.versionCount", n);
}

// Intl.DateTimeFormat instances are cached per locale and options: in hot
// paths (audit list, user list) they are called 100 times per render, and
// constructing a formatter per call costs ~2 ms per 50 rows.
const _dateFormats = new Map<string, Intl.DateTimeFormat>();

function dateFormat(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const tag = intlLocale();
  const key = `${tag}|${JSON.stringify(options)}`;
  let fmt = _dateFormats.get(key);
  if (!fmt) {
    fmt = new Intl.DateTimeFormat(tag, options);
    _dateFormats.set(key, fmt);
  }
  return fmt;
}

const DAY: Intl.DateTimeFormatOptions = { day: "numeric", month: "long", year: "numeric" };
const TIME: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit", second: "2-digit" };
// Date and time in one string, for version history and the stale-version
// banner. Separate from `formatDay`/`formatTime`, which split the value
// into two columns; here it must be one compact string in a row.
const DATE_TIME: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
};
const SHORT_DATE: Intl.DateTimeFormatOptions = { year: "numeric", month: "numeric", day: "numeric" };
const TIMESTAMP: Intl.DateTimeFormatOptions = {
  ...SHORT_DATE,
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
};

/** `null` for missing input and for an invalid date, so the call site
 * renders nothing instead of showing "Invalid Date" to the user. */
export function formatDateTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : dateFormat(DATE_TIME).format(d);
}

export function formatDay(iso: string): string {
  return dateFormat(DAY).format(new Date(iso));
}

export function formatTime(iso: string): string {
  return dateFormat(TIME).format(new Date(iso));
}

/** Numeric date ("24.09.2026", "9/24/2026"), the `toLocaleDateString()`
 * default, for compact row metadata. */
export function formatShortDate(iso: string): string {
  return dateFormat(SHORT_DATE).format(new Date(iso));
}

/** Numeric date with time, the `toLocaleString()` default. */
export function formatTimestamp(iso: string): string {
  return dateFormat(TIMESTAMP).format(new Date(iso));
}

/** "Updated <date>, <time>" overline above the document content.
 * Kept in `lib/` rather than a view because both views and the
 * `useVersionPreview` hook use it (lib must not import from views/). */
export function formatMeta(updatedAt: string | null | undefined): string | null {
  if (!updatedAt) return null;
  return t("format.updatedAt", { date: formatDay(updatedAt), time: formatTime(updatedAt) });
}

const _relativeFormats = new Map<string, Intl.RelativeTimeFormat>();
function relativeFormat(): Intl.RelativeTimeFormat {
  const tag = intlLocale();
  let fmt = _relativeFormats.get(tag);
  if (!fmt) {
    fmt = new Intl.RelativeTimeFormat(tag, { numeric: "auto" });
    _relativeFormats.set(tag, fmt);
  }
  return fmt;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY_MS = 24 * HOUR;

/** "5 minutes ago", "yesterday"; past a week the numeric date, because
 * "23 days ago" is harder to place than the date itself. */
export function formatRelative(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const diff = then - now;
  const abs = Math.abs(diff);
  const rtf = relativeFormat();
  if (abs < MINUTE) return rtf.format(0, "second");
  if (abs < HOUR) return rtf.format(Math.round(diff / MINUTE), "minute");
  if (abs < DAY_MS) return rtf.format(Math.round(diff / HOUR), "hour");
  if (abs < 7 * DAY_MS) return rtf.format(Math.round(diff / DAY_MS), "day");
  return formatShortDate(iso);
}

function localDayNumber(d: Date): number {
  return Math.round(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY_MS);
}

/** Heading of a day group: "Today", "Yesterday" (from Intl, in the current
 * locale), otherwise the date. */
export function formatDayHeading(iso: string, now: Date = new Date()): string {
  const days = localDayNumber(new Date(iso)) - localDayNumber(now);
  if (days !== 0 && days !== -1) return formatDay(iso);
  const text = relativeFormat().format(days, "day");
  return text.charAt(0).toLocaleUpperCase(intlLocale()) + text.slice(1);
}
