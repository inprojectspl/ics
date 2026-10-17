/**
 * Informational password strength (ADR-0007): a rough entropy estimate, not a
 * character-class checklist, and it never blocks a submit. The server only
 * enforces a minimum length.
 */

import { t } from "./i18n";

type StrengthScore = 0 | 1 | 2 | 3;

export interface PasswordStrength {
  score: StrengthScore;
  label: string;
  hint: string;
  /** Rough log2 of the guesses needed. Exposed for tests and tuning. */
  bits: number;
}

/** Guessed first by any attacker, whatever their length. */
const COMMON = [
  "password",
  "passw0rd",
  "haslo",
  "hasło",
  "qwerty",
  "qwertyuiop",
  "123456",
  "12345678",
  "123456789",
  "admin",
  "administrator",
  "letmein",
  "welcome",
  "iloveyou",
  "monkey",
  "dragon",
  "zaq12wsx",
  "1qaz2wsx",
  "secret",
  "test",
];

const SEQUENCES = ["abcdefghijklmnopqrstuvwxyz", "0123456789", "qwertyuiop", "asdfghjkl", "zxcvbnm"];

/** Size of the character space the password draws from. */
function alphabetSize(password: string): number {
  let size = 0;
  if (/[a-z]/.test(password)) size += 26;
  if (/[A-Z]/.test(password)) size += 26;
  if (/[0-9]/.test(password)) size += 10;
  if (/[^a-zA-Z0-9]/.test(password)) size += 33;
  return size || 1;
}

/** True when the password is a run of one repeated character or chunk. */
function isRepetitive(password: string): boolean {
  const lower = password.toLowerCase();
  if (/^(.)\1+$/.test(lower)) return true;
  for (let unit = 2; unit <= lower.length / 2; unit++) {
    if (lower.length % unit !== 0) continue;
    const chunk = lower.slice(0, unit);
    if (chunk.repeat(lower.length / unit) === lower) return true;
  }
  return false;
}

/** True when a keyboard or alphabet run of 4+ characters shows up. */
function hasSequence(password: string): boolean {
  const lower = password.toLowerCase();
  for (const row of SEQUENCES) {
    for (let i = 0; i + 4 <= row.length; i++) {
      const run = row.slice(i, i + 4);
      if (lower.includes(run) || lower.includes([...run].reverse().join(""))) return true;
    }
  }
  return false;
}

/** Strips the decorations people add to a base word: caps, digits, trailing symbols. */
function baseWord(password: string): string {
  return password
    .toLowerCase()
    .replace(/[0-9]+$/, "")
    .replace(/[^a-ząćęłńóśźż]/g, "")
    .replace(/4/g, "a")
    .replace(/3/g, "e")
    .replace(/0/g, "o")
    .replace(/1/g, "l");
}

export function estimatePasswordStrength(password: string): PasswordStrength {
  if (password.length === 0) {
    return { score: 0, label: "", hint: "", bits: 0 };
  }

  // Compared in three shapes, because "Zaq12wsx!" is the same guess as
  // "zaq12wsx": as typed, stripped of decoration, and reduced to its word.
  const lower = password.toLowerCase();
  const stripped = lower.replace(/[^a-z0-9ąćęłńóśźż]/g, "");
  const base = baseWord(password);
  const isCommon = [lower, stripped, base].some((form) => form.length > 0 && COMMON.includes(form));

  if (isCommon) {
    return {
      score: 0,
      label: t("passwordStrength.veryWeak"),
      hint: t("passwordStrength.hintCommon"),
      bits: 8,
    };
  }

  let bits = password.length * Math.log2(alphabetSize(password));

  // A word with a year or a few digits bolted on is barely harder to guess
  // than the word itself, so most of the length stops counting.
  if (/^[a-zA-Ząćęłńóśźż]+[0-9!@#$%^&*._-]{0,4}$/.test(password)) bits *= 0.55;
  if (isRepetitive(password)) bits = Math.min(bits, 12);
  if (hasSequence(password)) bits *= 0.6;

  // A passphrase: several words separated by spaces. Length here is real.
  const words = password.trim().split(/\s+/).filter((w) => w.length > 1);
  if (words.length >= 3) bits = Math.max(bits, words.length * 11);

  bits = Math.round(bits);

  if (bits < 30) {
    return {
      score: 0,
      label: t("passwordStrength.veryWeak"),
      hint: t("passwordStrength.hintInstant"),
      bits,
    };
  }
  if (bits < 45) {
    return { score: 1, label: t("passwordStrength.weak"), hint: t("passwordStrength.hintWeak"), bits };
  }
  if (bits < 65) {
    return { score: 2, label: t("passwordStrength.fair"), hint: t("passwordStrength.hintFair"), bits };
  }
  return { score: 3, label: t("passwordStrength.strong"), hint: t("passwordStrength.hintStrong"), bits };
}
