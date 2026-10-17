import { describe, expect, it } from "vitest";

import { setLocale } from "./i18n";
import { estimatePasswordStrength } from "./passwordStrength";

describe("estimatePasswordStrength", () => {
  it("does not rate an empty field", () => {
    const s = estimatePasswordStrength("");
    expect(s.label).toBe("");
    expect(s.score).toBe(0);
  });

  it("knows passwords from guessing lists", () => {
    for (const pw of ["password", "haslo", "qwerty", "123456789", "admin"]) {
      expect(estimatePasswordStrength(pw).score, pw).toBe(0);
    }
  });

  it("does not let decoration save a known pattern", () => {
    // "Zaq12wsx!" falls to the same guess as "zaq12wsx".
    expect(estimatePasswordStrength("Zaq12wsx!").score).toBe(0);
    expect(estimatePasswordStrength("Haslo!").score).toBe(0);
  });

  it("accepts a long all-lowercase password", () => {
    // No uppercase or digits is not disqualifying; length is what counts.
    expect(estimatePasswordStrength("dlugiehaslobezcyfr").score).toBeGreaterThanOrEqual(2);
  });

  it("rates a word with an appended year only slightly above the word", () => {
    const word = estimatePasswordStrength("kwiatuszek");
    const withYear = estimatePasswordStrength("kwiatuszek2026");
    expect(withYear.bits).toBeLessThan(word.bits * 2);
    expect(withYear.score).toBeLessThanOrEqual(1);
  });

  it("gives no strength for repetitions and sequences", () => {
    expect(estimatePasswordStrength("aaaaaaaaaaaa").score).toBe(0);
    expect(estimatePasswordStrength("abababababab").score).toBe(0);
    expect(estimatePasswordStrength("qwertyuiop12").score).toBeLessThanOrEqual(1);
  });

  it("rates a long phrase above a short password full of special characters", () => {
    const fancy = estimatePasswordStrength("P@ss1!");
    const phrase = estimatePasswordStrength("kubek herbaty na parapecie");
    expect(phrase.bits).toBeGreaterThan(fancy.bits);
    expect(phrase.score).toBe(3);
  });

  it("rates higher as the length grows", () => {
    const scores = ["ghjkwert", "ghjkwertmnbv", "ghjkwertmnbvxzas"].map(
      (p) => estimatePasswordStrength(p).bits,
    );
    expect(scores[1]!).toBeGreaterThan(scores[0]!);
    expect(scores[2]!).toBeGreaterThan(scores[1]!);
  });

  it("rates a random password-manager password as strong", () => {
    expect(estimatePasswordStrength("xK7#pQ2mZr9!Lw").score).toBe(3);
  });

  it("returns a label and a hint for every level", () => {
    for (const pw of ["krotkie1", "ghjkwertmnbv", "ghjkwertmnbvxzas", "xK7#pQ2mZr9!Lw"]) {
      const s = estimatePasswordStrength(pw);
      expect(s.label, pw).not.toBe("");
      expect(s.hint, pw).not.toBe("");
    }
  });
});

describe("estimatePasswordStrength in English", () => {
  it("returns the label and hint in the active locale", () => {
    setLocale("en", { persist: false });
    const common = estimatePasswordStrength("password");
    expect(common.label).toBe("Very weak");
    expect(common.hint).toBe("This password is on every guessing list.");
    const strong = estimatePasswordStrength("correct horse battery staple");
    expect(strong.label).toBe("Strong");
    expect(strong.hint).toBe("Hard to guess.");
  });
});
