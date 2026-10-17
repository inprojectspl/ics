import { beforeEach, describe, it, expect } from "vitest";
import { setLocale } from "./i18n";
import {
  formatBytes,
  formatDateTime,
  formatDay,
  formatDayHeading,
  formatMeta,
  formatRelative,
  formatShortDate,
  formatTime,
  kindLabel,
  versionCountLabel,
} from "./format";

describe("versionCountLabel in Polish", () => {
  beforeEach(() => setLocale("pl", { persist: false }));

  it("uses the singular for one", () => {
    expect(versionCountLabel(1)).toBe("1 wersja");
  });

  it("uses the few form for 2-4", () => {
    expect(versionCountLabel(2)).toBe("2 wersje");
    expect(versionCountLabel(23)).toBe("23 wersje");
  });

  it("uses the many form for 5 and more", () => {
    expect(versionCountLabel(5)).toBe("5 wersji");
    expect(versionCountLabel(21)).toBe("21 wersji");
  });

  it("treats 12-14 as many, not few", () => {
    expect(versionCountLabel(12)).toBe("12 wersji");
    expect(versionCountLabel(14)).toBe("14 wersji");
  });
});

describe("formatBytes", () => {
  it("returns '0 B' for null / undefined", () => {
    expect(formatBytes(null)).toBe("0 B");
    expect(formatBytes(undefined)).toBe("0 B");
  });

  it("formats bytes below 1 KB", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
  });

  it("formats KB with the locale's decimal separator", () => {
    expect(formatBytes(2048)).toBe("2.0 KB");
    setLocale("pl", { persist: false });
    expect(formatBytes(2048)).toBe("2,0 KB");
  });

  it("formats MB", () => {
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});

describe("kindLabel", () => {
  it("maps md_single to 'Markdown'", () => {
    expect(kindLabel("md_single")).toBe("Markdown");
  });

  it("maps md_collection to 'Collection'", () => {
    expect(kindLabel("md_collection")).toBe("Collection");
  });

  it("maps html_bundle to 'HTML bundle'", () => {
    expect(kindLabel("html_bundle")).toBe("HTML bundle");
  });

  it("maps pdf_doc to 'PDF'", () => {
    expect(kindLabel("pdf_doc")).toBe("PDF");
  });

  it("maps office_doc to 'Document'", () => {
    expect(kindLabel("office_doc")).toBe("Document");
  });
});

describe("formatDay", () => {
  it("formats the date with the year and the month name", () => {
    const out = formatDay("2026-06-01T10:00:00Z");
    expect(out).toContain("2026");
    expect(out).toMatch(/June/);
  });
});

describe("formatTime", () => {
  it("formats the time as hh:mm:ss with the day period", () => {
    expect(formatTime("2026-06-01T13:05:09Z")).toMatch(/^\d{2}:\d{2}:\d{2}\s[AP]M$/);
  });
});

describe("dates follow the active locale", () => {
  const iso = "2026-06-01T13:05:09Z";

  it("formats in Polish after a switch", () => {
    setLocale("pl", { persist: false });
    expect(formatDay(iso)).toMatch(/czerwca/);
    expect(formatDateTime(iso)).toMatch(/cze/);
    expect(formatMeta(iso)).toMatch(/^Zaktualizowano .*czerwca/);
    expect(kindLabel("md_collection")).toBe("Kolekcja");
    expect(versionCountLabel(2)).toBe("2 wersje");
  });

  it("formats in English by default", () => {
    expect(formatDay(iso)).toMatch(/June/);
    expect(formatShortDate(iso)).toBe("6/1/2026");
    expect(formatMeta(iso)).toMatch(/^Updated June 1, 2026/);
  });

  it("returns null for an invalid date", () => {
    expect(formatDateTime("nope")).toBeNull();
  });
});

describe("formatRelative", () => {
  const now = Date.parse("2026-09-28T12:00:00Z");
  const ago = (ms: number) => new Date(now - ms).toISOString();

  it("says now for under a minute", () => {
    expect(formatRelative(ago(20_000), now)).toBe("now");
  });

  it("counts minutes, hours and days in the current locale", () => {
    expect(formatRelative(ago(5 * 60_000), now)).toBe("5 minutes ago");
    expect(formatRelative(ago(3 * 3_600_000), now)).toBe("3 hours ago");
    expect(formatRelative(ago(86_400_000), now)).toBe("yesterday");
    setLocale("pl", { persist: false });
    expect(formatRelative(ago(2 * 60_000), now)).toBe("2 minuty temu");
    expect(formatRelative(ago(2 * 86_400_000), now)).toBe("przedwczoraj");
  });

  it("falls back to the date past a week and to nothing for garbage", () => {
    expect(formatRelative(ago(10 * 86_400_000), now)).toBe(formatShortDate(ago(10 * 86_400_000)));
    expect(formatRelative("nope", now)).toBe("");
  });
});

describe("formatDayHeading", () => {
  const now = new Date("2026-09-28T12:00:00Z");

  it("names today and yesterday in the current locale and dates the rest", () => {
    expect(formatDayHeading("2026-09-28T08:00:00Z", now)).toBe("Today");
    expect(formatDayHeading("2026-09-27T20:00:00Z", now)).toBe("Yesterday");
    expect(formatDayHeading("2026-09-01T10:00:00Z", now)).toBe(formatDay("2026-09-01T10:00:00Z"));
    setLocale("pl", { persist: false });
    expect(formatDayHeading("2026-09-27T20:00:00Z", now)).toBe("Wczoraj");
  });
});
