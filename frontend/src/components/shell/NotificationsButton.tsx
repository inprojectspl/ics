import { useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { t, tn } from "../../lib/i18n";
import { playEnter } from "../../lib/motion";
import { useUnreadCount } from "../../lib/notifications/queries";
import { badgeLabel } from "../../lib/notifications/titleBadge";
import { MenuNotifications } from "../notifications/MenuNotifications";
import { iconButtonClass } from "../ui/IconButton";
import { Popover } from "../ui/Popover";

/**
 * The one global action of the bar: the inbox (ADR-0023). The count sits on
 * the bell; a rise bumps it once, which is the whole animation.
 */
export function NotificationsButton() {
  const count = useUnreadCount();
  const unread = count ?? 0;
  const badgeRef = useRef<HTMLSpanElement>(null);
  // A rise of the count bumps the badge; the first load does not.
  const [seen, setSeen] = useState({ count, bump: 0 });
  if (seen.count !== count) {
    const rose = seen.count !== undefined && count !== undefined && count > seen.count;
    setSeen({ count, bump: rose ? seen.bump + 1 : seen.bump });
  }
  useEffect(() => {
    if (seen.bump > 0) playEnter(badgeRef.current, "bump");
  }, [seen.bump]);

  const label = unread > 0 ? tn("notifications.openUnread", unread) : t("notifications.title");
  return (
    <Popover
      label={t("notifications.title")}
      align="end"
      widthClass="w-[26rem]"
      trigger={(props) => (
        <button type="button" {...props} aria-label={label} title={label} className={iconButtonClass("ghost")}>
          <Bell size={18} aria-hidden />
          {unread > 0 && (
            <span
              ref={badgeRef}
              aria-hidden
              className="absolute right-0.5 top-0.5 min-w-4 rounded-full bg-accent px-1 text-center text-[10px] font-semibold leading-4 text-on-accent tabular-nums ring-2 ring-surface"
            >
              {badgeLabel(unread)}
            </span>
          )}
        </button>
      )}
    >
      {({ close }) => <MenuNotifications unread={unread} onClose={close} />}
    </Popover>
  );
}
