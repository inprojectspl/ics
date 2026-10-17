/**
 * Typed `t()` over flat JSON catalogues (ADR-0010). The locale is module
 * state, so `t()` works outside components; switching it remounts the tree
 * under `<LocaleRoot>` to re-render every string.
 */
import { Fragment, createElement, useSyncExternalStore, type ReactNode } from "react";
import en from "../locales/en.json";
import pl from "../locales/pl.json";

export type Locale = "pl" | "en";

const FALLBACK: Locale = "en";
const STORAGE_KEY = "ics-locale";

interface PluralForms {
  one: string;
  few?: string;
  many?: string;
  other: string;
}

type Catalogue = typeof pl;
type Entry = string | PluralForms;

/** Keys of plain strings. The Polish catalogue is the type source; the key
 * parity test keeps `en.json` in step. */
export type MessageKey = {
  [K in keyof Catalogue]: Catalogue[K] extends string ? K : never;
}[keyof Catalogue];

/** Keys of plural entries (objects with CLDR category forms). */
export type PluralKey = Exclude<keyof Catalogue, MessageKey>;

export type Vars = Readonly<Record<string, string | number>>;

const CATALOGUES: Readonly<Record<Locale, Readonly<Record<string, Entry>>>> = { pl, en };

function isLocale(value: unknown): value is Locale {
  return value === "pl" || value === "en";
}

/** First supported language from the browser's preference list, English
 * when none matches. */
export function detectLocale(languages: readonly string[]): Locale {
  for (const tag of languages) {
    const base = tag.toLowerCase().split("-")[0];
    if (isLocale(base)) return base;
  }
  return FALLBACK;
}

function browserLanguages(): readonly string[] {
  if (typeof navigator === "undefined") return [];
  return navigator.languages?.length ? navigator.languages : [navigator.language];
}

function storedLocale(): Locale | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return isLocale(saved) ? saved : null;
  } catch {
    return null;
  }
}

let current: Locale = storedLocale() ?? detectLocale(browserLanguages());
const listeners = new Set<() => void>();

function syncDocumentLang(): void {
  if (typeof document !== "undefined") document.documentElement.lang = current;
}
syncDocumentLang();

export function getLocale(): Locale {
  return current;
}

/** Change the active locale. `persist` is false only for tests and the
 * initial sync; a user choice is always stored. */
export function setLocale(locale: Locale, { persist = true } = {}): void {
  if (persist) {
    try {
      localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      /* storage blocked: the choice lasts for this page only */
    }
  }
  if (locale === current) return;
  current = locale;
  syncDocumentLang();
  for (const fn of listeners) fn();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useLocale(): Locale {
  return useSyncExternalStore(subscribe, getLocale, getLocale);
}

/** Remounts its children when the locale changes, so strings computed with
 * `t()` during render (including in memoised rows) are recomputed. */
export function LocaleRoot({ children }: { children: ReactNode }) {
  const locale = useLocale();
  return createElement(Fragment, { key: locale }, children);
}

/** BCP 47 tag for `Intl`: the browser's own regional variant of the active
 * language when it has one (`en-GB`), otherwise the bare language. */
export function intlLocale(): string {
  for (const tag of browserLanguages()) {
    if (tag.toLowerCase().split("-")[0] === current) return tag;
  }
  return current;
}

/** Compares names the way lists of the app sort them: app language, case
 * and accents ignored, numbers by value ("R-2" before "R-10"). */
export function nameCollator(): Intl.Collator {
  return new Intl.Collator(intlLocale(), { sensitivity: "base", numeric: true });
}

function lookup(key: string): Entry | undefined {
  return CATALOGUES[current][key] ?? CATALOGUES[FALLBACK][key];
}

function interpolate(text: string, vars: Vars | undefined): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = vars[name];
    return value === undefined ? match : String(value);
  });
}

/** Narrows a key built at runtime (e.g. from an API error code). */
export function hasMessage(key: string): key is MessageKey {
  return typeof CATALOGUES[FALLBACK][key] === "string";
}

/** Translate `key`, replacing `{name}` placeholders from `vars`. */
export function t(key: MessageKey, vars?: Vars): string {
  const entry = lookup(key);
  return typeof entry === "string" ? interpolate(entry, vars) : key;
}

const pluralRules = new Map<string, Intl.PluralRules>();

function pluralCategory(count: number): Intl.LDMLPluralRule {
  let rules = pluralRules.get(current);
  if (!rules) {
    rules = new Intl.PluralRules(current);
    pluralRules.set(current, rules);
  }
  return rules.select(count);
}

/** Plural form for `count` by the locale's CLDR rules (Polish: one, few,
 * many). `{count}` in the form is the locale-formatted number. */
export function tn(key: PluralKey, count: number, vars?: Vars): string {
  const entry = lookup(key);
  if (entry === undefined || typeof entry === "string") return key;
  const category = pluralCategory(count);
  const form =
    (category === "one" || category === "few" || category === "many" ? entry[category] : undefined) ??
    entry.other;
  return interpolate(form, { count: formatNumber(count), ...vars });
}

const numberFormats = new Map<string, Intl.NumberFormat>();

export function formatNumber(n: number, options?: Intl.NumberFormatOptions): string {
  const tag = intlLocale();
  const cacheKey = `${tag}|${JSON.stringify(options ?? {})}`;
  let fmt = numberFormats.get(cacheKey);
  if (!fmt) {
    fmt = new Intl.NumberFormat(tag, options);
    numberFormats.set(cacheKey, fmt);
  }
  return fmt.format(n);
}
