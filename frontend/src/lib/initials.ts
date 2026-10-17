/** Two letters for an avatar: first and last word of the name, else the
 * start of the e-mail. */
export function initials(displayName: string | null | undefined, email: string): string {
  const source = (displayName ?? "").trim() || email;
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  const letters = parts.length > 1 ? `${parts[0]?.[0] ?? ""}${parts[1]?.[0] ?? ""}` : source.slice(0, 2);
  return letters.toUpperCase();
}
