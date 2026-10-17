import { describe, expect, it } from "vitest";
import { pageTitle, setPageTitle, setTitlePrefix } from "./documentTitle";

describe("documentTitle", () => {
  it("keeps the page title and the prefix apart", () => {
    document.title = "ICS - Internal Content Sharing";
    expect(pageTitle()).toBe("ICS - Internal Content Sharing");
    setTitlePrefix("(2) ");
    expect(document.title).toBe("(2) ICS - Internal Content Sharing");
    setPageTitle("(1) Intro - ICS");
    expect(document.title).toBe("(2) (1) Intro - ICS");
    expect(pageTitle()).toBe("(1) Intro - ICS");
    setTitlePrefix("");
    expect(document.title).toBe("(1) Intro - ICS");
  });
});
