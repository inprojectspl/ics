import { describe, expect, it } from "vitest";

import type { RelationType } from "../api";
import { setLocale, t } from "./i18n";
import { RELATION_LABEL, relationLabelKey } from "./relationLabels";

// [type, out (en), in (en)]
const CASES: [RelationType, string, string][] = [
  ["derived_from", "Derived from", "Basis for"],
  ["supersedes", "Supersedes", "Superseded by"],
  ["depends_on", "Depends on", "Required by"],
  ["part_of", "Part of", "Has part"],
  ["references", "References", "Referenced by"],
  ["duplicates", "Duplicates", "Duplicated by"],
  ["relates_to", "Related to", "Related to"],
  ["contradicts", "Contradicts", "Contradicts"],
];

describe("relationLabelKey", () => {
  it.each(CASES)("%s reads as its label from both ends", (type, out, inbound) => {
    setLocale("en", { persist: false });
    expect(t(relationLabelKey(type, "out"))).toBe(out);
    expect(t(relationLabelKey(type, "in"))).toBe(inbound);
  });

  it("uses the Polish labels too", () => {
    setLocale("pl", { persist: false });
    expect(t(relationLabelKey("derived_from", "out"))).toBe("Powstał na podstawie");
    expect(t(relationLabelKey("derived_from", "in"))).toBe("Jest podstawą dla");
  });

  it("gives symmetric types one key and directed types two", () => {
    for (const [type] of CASES) {
      const same = relationLabelKey(type, "out") === relationLabelKey(type, "in");
      expect(same, type).toBe(type === "relates_to" || type === "contradicts");
    }
  });

  it("reads inverse labels through the shared map", () => {
    expect(relationLabelKey("derived_from", "in")).toBe(RELATION_LABEL.basis_for);
    expect(relationLabelKey("part_of", "in")).toBe(RELATION_LABEL.has_part);
  });
});
