import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import en from "../locales/en.json";
import pl from "../locales/pl.json";
import {
  LocaleRoot,
  detectLocale,
  getLocale,
  hasMessage,
  intlLocale,
  setLocale,
  t,
  tn,
  type PluralKey,
} from "./i18n";

type Raw = Record<string, unknown>;

// Forms each locale needs by its CLDR plural rules (integers only).
const REQUIRED_FORMS: Record<string, string[]> = {
  pl: ["one", "few", "many", "other"],
  en: ["one", "other"],
};

describe("catalogues", () => {
  it("pl and en have the same keys", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(pl).sort());
  });

  it.each([
    ["pl", pl as Raw],
    ["en", en as Raw],
  ])("%s has no empty values and no long dashes", (_locale, catalogue) => {
    for (const [key, value] of Object.entries(catalogue)) {
      const texts = typeof value === "string" ? [value] : Object.values(value as Raw);
      for (const text of texts) {
        expect(typeof text, key).toBe("string");
        expect((text as string).trim(), key).not.toBe("");
        expect(text as string, key).not.toMatch(/[\u2013\u2014]/);
      }
    }
  });

  it.each([
    ["pl", pl as Raw],
    ["en", en as Raw],
  ])("%s plural entries have every form its rules need", (locale, catalogue) => {
    const plEntries = pl as Raw;
    for (const [key, value] of Object.entries(catalogue)) {
      // A key is plural in both catalogues or in neither.
      expect(typeof value, key).toBe(typeof plEntries[key]);
      if (typeof value === "string") continue;
      expect(Object.keys(value as Raw), key).toEqual(
        expect.arrayContaining(REQUIRED_FORMS[locale] ?? []),
      );
    }
  });
});

describe("detectLocale", () => {
  it("picks the first supported browser language", () => {
    expect(detectLocale(["de-DE", "pl-pl", "en-US"])).toBe("pl");
    expect(detectLocale(["en-GB", "pl"])).toBe("en");
  });

  it("falls back to English for unsupported languages", () => {
    expect(detectLocale(["de-DE", "fr"])).toBe("en");
    expect(detectLocale([])).toBe("en");
  });
});

describe("setLocale", () => {
  it("persists the choice and updates <html lang>", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    setLocale("pl");
    expect(getLocale()).toBe("pl");
    expect(document.documentElement.lang).toBe("pl");
    expect(localStorage.getItem("ics-locale")).toBe("pl");
    setItem.mockRestore();
  });

  it("survives blocked storage", () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => setLocale("en")).not.toThrow();
    expect(getLocale()).toBe("en");
  });
});

describe("t / tn", () => {
  it("interpolates placeholders", () => {
    expect(t("format.updatedAt", { date: "May 1", time: "10:00" })).toBe(
      "Updated May 1, 10:00",
    );
  });

  it("uses Polish plural forms for 1, 2, 5 and 12", () => {
    setLocale("pl", { persist: false });
    const key: PluralKey = "format.versionCount";
    expect(tn(key, 1)).toBe("1 wersja");
    expect(tn(key, 2)).toBe("2 wersje");
    expect(tn(key, 5)).toBe("5 wersji");
    expect(tn(key, 12)).toBe("12 wersji");
    expect(tn(key, 22)).toBe("22 wersje");
  });

  it("uses English plural forms", () => {
    expect(tn("format.versionCount", 1)).toBe("1 version");
    expect(tn("format.versionCount", 5)).toBe("5 versions");
  });

  it("recognises catalogue keys built at runtime", () => {
    expect(hasMessage("kind.mdSingle")).toBe(true);
    expect(hasMessage("format.versionCount")).toBe(false);
    expect(hasMessage("kind.nope")).toBe(false);
  });
});

describe("intlLocale", () => {
  it("prefers the browser's regional variant of the active language", () => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["en-GB", "pl-pl"]);
    expect(intlLocale()).toBe("en-GB");
    setLocale("pl", { persist: false });
    expect(intlLocale()).toBe("pl-pl");
  });

  it("uses the bare language when the browser has no variant of it", () => {
    vi.spyOn(navigator, "languages", "get").mockReturnValue(["de-DE"]);
    expect(intlLocale()).toBe("en");
  });
});

describe("LocaleRoot", () => {
  it("re-renders its subtree in the new locale", () => {
    function Label() {
      return <span>{t("kind.mdCollection")}</span>;
    }
    render(
      <LocaleRoot>
        <Label />
      </LocaleRoot>,
    );
    expect(screen.getByText("Collection")).toBeInTheDocument();
    act(() => setLocale("pl", { persist: false }));
    expect(screen.getByText("Kolekcja")).toBeInTheDocument();
  });
});
