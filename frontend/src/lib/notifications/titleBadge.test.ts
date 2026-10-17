import { afterEach, describe, expect, it, vi } from "vitest";
import { setPageTitle } from "../documentTitle";
import { badgeLabel, setAppBadge, setTitleCount } from "./titleBadge";

afterEach(() => {
  setTitleCount(0);
  setPageTitle("ICS");
});

describe("title prefix", () => {
  it("prefixes the unread count and keeps it across a page title change", () => {
    setPageTitle("ICS");
    setTitleCount(3);
    expect(document.title).toBe("(3) ICS");
    setPageTitle("Plan - ICS");
    expect(document.title).toBe("(3) Plan - ICS");
    setTitleCount(120);
    expect(document.title).toBe("(99+) Plan - ICS");
    setTitleCount(0);
    expect(document.title).toBe("Plan - ICS");
  });

  it("caps the badge at 99+", () => {
    expect(badgeLabel(99)).toBe("99");
    expect(badgeLabel(100)).toBe("99+");
  });
});

describe("setAppBadge", () => {
  it("sets and clears the installed app badge where supported", () => {
    const set = vi.fn().mockResolvedValue(undefined);
    const clear = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { setAppBadge: set, clearAppBadge: clear });
    setAppBadge(4);
    setAppBadge(0);
    expect(set).toHaveBeenCalledWith(4);
    expect(clear).toHaveBeenCalled();
    Object.assign(navigator, { setAppBadge: () => { throw new Error("blocked"); } });
    expect(() => setAppBadge(1)).not.toThrow();
    Object.assign(navigator, { setAppBadge: undefined, clearAppBadge: undefined });
  });
});
