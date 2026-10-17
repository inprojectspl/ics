/** Lower case without diacritics, so "dzial" finds "Dział" (ł has no decomposition). */
export function foldText(s: string): string {
  return s.normalize("NFD").replace(/\p{Diacritic}/gu, "").replace(/ł/g, "l").replace(/Ł/g, "l").toLowerCase();
}

/** Whether `text` contains the typed `query`, ignoring case and diacritics. */
export function matchesText(text: string, query: string): boolean {
  const q = foldText(query.trim());
  return q === "" || foldText(text).includes(q);
}
