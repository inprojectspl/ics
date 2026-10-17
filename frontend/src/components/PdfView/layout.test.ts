import { describe, expect, it } from "vitest";
import { loadErrorKey } from "./layout";

describe("loadErrorKey", () => {
  it.each([
    [{ name: "PasswordException" }, "pdfView.errorPassword"],
    [{ name: "InvalidPDFException" }, "pdfView.errorInvalid"],
    [{ name: "ResponseException" }, "pdfView.errorLoad"],
    ["boom", "pdfView.errorLoad"],
    [null, "pdfView.errorLoad"],
  ])("maps %o to %s", (err, key) => {
    expect(loadErrorKey(err)).toBe(key);
  });
});
