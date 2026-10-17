import { Keyboard } from "lucide-react";

import { IconButton } from "../../components/ui/IconButton";
import { Kbd } from "../../components/ui/Kbd";
import { Popover } from "../../components/ui/Popover";
import { t } from "../../lib/i18n";

/** Keys and what they do, translated when the help opens. */
export function shortcuts(): Array<[string[], string]> {
  const newTab = t("graphExplorer.shortcutNewTab");
  return [
    [["Ctrl/⌘", t("graphExplorer.keyClick")], newTab],
    [[t("graphExplorer.keyMiddleClick")], newTab],
    [["Enter"], t("graphExplorer.shortcutOpen")],
    [["Ctrl/⌘", "Enter"], newTab],
    [["E"], t("graphExplorer.shortcutExpand")],
    [[t("graphExplorer.keySpace")], t("graphExplorer.shortcutExpand")],
    [["/"], t("graphExplorer.shortcutSearch")],
    [["F"], t("graphExplorer.shortcutFocus")],
    [["P"], t("graphExplorer.shortcutPanel")],
    [["Esc"], t("graphExplorer.shortcutEscape")],
  ];
}

/** The explorer's keyboard and mouse shortcuts, behind a keyboard icon. */
export function ShortcutsHelp() {
  return (
    <Popover
      label={t("graphExplorer.shortcuts")}
      align="end"
      widthClass="w-[21rem]"
      trigger={(p) => (
        // The tooltip goes left: below, it would cover the open list.
        <IconButton {...p} size="sm" tooltipSide="left" label={t("graphExplorer.shortcuts")} icon={<Keyboard size={16} aria-hidden />} />
      )}
    >
      {() => (
        <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-meta">
          {shortcuts().map(([keys, label], i) => (
            <div key={i} className="contents">
              <dt className="flex items-center gap-1 whitespace-nowrap">
                {keys.map((k) => (
                  <Kbd key={k}>{k}</Kbd>
                ))}
              </dt>
              <dd className="text-text-secondary">{label}</dd>
            </div>
          ))}
        </dl>
      )}
    </Popover>
  );
}
