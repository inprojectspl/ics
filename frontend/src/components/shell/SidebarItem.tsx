import { clsx } from "clsx";
import { AppLink } from "../ui/AppLink";

interface Props {
  href: string;
  label: string;
  active: boolean;
  onNavigate?: () => void;
}

/** Second-level entry of the navigation tree (a view, a project). */
export function SidebarItem({ href, label, active, onNavigate }: Props) {
  return (
    <li>
      <AppLink
        href={href}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        title={label}
        className={clsx(
          "relative flex min-h-8 items-center rounded-control py-1.5 pl-9 pr-2 text-ui",
          "transition-colors duration-150 ease-standard",
          active
            ? "bg-accent-soft font-medium text-text-primary"
            : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
        )}
      >
        {/* Position marker: the active entry is told by fill, weight and this bar. */}
        <span
          aria-hidden
          className={clsx(
            "absolute left-[1.3rem] top-1.5 bottom-1.5 w-0.5 rounded-full",
            active ? "bg-accent" : "bg-border",
          )}
        />
        <span className="truncate">{label}</span>
      </AppLink>
    </li>
  );
}
