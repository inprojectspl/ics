import { describe, expect, it } from "vitest";

import { t } from "../../lib/i18n";
import { shortcuts } from "./ShortcutsHelp";

describe("graph explorer shortcuts help", () => {
  it("lists Space next to E, as the key handler treats them alike", () => {
    const expand = shortcuts().filter(([, label]) => label === t("graphExplorer.shortcutExpand"));
    expect(expand.map(([keys]) => keys)).toEqual([["E"], [t("graphExplorer.keySpace")]]);
  });
});
