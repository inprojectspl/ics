import { useId, useRef, useState } from "react";
import { clsx } from "clsx";
import { ChevronRight } from "lucide-react";
import { t } from "../../lib/i18n";
import { useEnterMotion } from "../../lib/motion";
import { navigate } from "../../lib/navigate";
import { INPROJECTS_URL } from "../BuiltBy";
import { InProjectsLogo } from "../InProjectsLogo";
import { AppLink } from "../ui/AppLink";
import { Menu } from "../ui/Menu";
import { useTooltip } from "../ui/Tooltip";
import type { NavGroup, NavLeaf } from "./navModel";
import { SidebarItem } from "./SidebarItem";

function leafLabel(leaf: NavLeaf): string {
  return typeof leaf.label === "string" ? t(leaf.label) : leaf.label.text;
}

interface Props {
  group: NavGroup;
  /** The group holds the current page (its leaf, or a page below it). */
  active: boolean;
  activeLeaf: string | null;
  expanded: boolean;
  onToggle: () => void;
  onNavigate?: () => void;
}

/**
 * A module of the navigation tree. The name is a link to the module; the
 * chevron next to it is a separate button that only folds the list, so a
 * click never has two meanings.
 */
export function SidebarGroup({ group, active, activeLeaf, expanded, onToggle, onNavigate }: Props) {
  const listId = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const [touched, setTouched] = useState(false);
  useEnterMotion(listRef, "reveal", expanded && touched);
  const label = t(group.label);
  const Icon = group.icon;
  const rootIsLeaf = group.children.some((c) => c.href === group.href && c.id === activeLeaf);

  return (
    <li>
      <div className="group/row flex items-center gap-0.5">
        <AppLink
          href={group.href}
          onClick={onNavigate}
          aria-current={active && rootIsLeaf ? "page" : undefined}
          className={clsx(
            "flex min-h-9 min-w-0 flex-1 items-center gap-2.5 rounded-control px-2 py-1.5 text-ui",
            "transition-colors duration-150 ease-standard",
            active ? "font-semibold text-text-primary" : "font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary",
          )}
        >
          <Icon size={18} aria-hidden className={clsx("shrink-0", active ? "text-accent" : "text-text-secondary")} />
          <span className="truncate">{label}</span>
        </AppLink>
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-label={t(expanded ? "shell.collapseGroup" : "shell.expandGroup", { name: label })}
          onClick={() => {
            setTouched(true);
            onToggle();
          }}
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-control text-text-secondary transition-colors duration-150 hover:bg-surface-hover hover:text-text-primary"
        >
          <ChevronRight
            size={16}
            aria-hidden
            className={clsx("transition-transform duration-150 ease-standard", expanded && "rotate-90")}
          />
        </button>
      </div>
      <ul ref={listRef} id={listId} hidden={!expanded} className="mt-0.5 mb-1.5 space-y-0.5">
        {group.children.map((leaf) => (
          <SidebarItem
            key={leaf.id}
            href={leaf.href}
            label={leafLabel(leaf)}
            active={leaf.id === activeLeaf}
            onNavigate={onNavigate}
          />
        ))}
      </ul>
    </li>
  );
}

/**
 * The same group in the collapsed rail: one icon with a tooltip. Its
 * entries open in a flyout menu on click or Enter, never on hover alone.
 */
export function SidebarRailGroup({ group, active, activeLeaf }: Pick<Props, "group" | "active" | "activeLeaf">) {
  const label = t(group.label);
  const Icon = group.icon;
  const tip = useTooltip(label, { side: "right" });
  const actions = group.children.map((leaf) => ({
    key: leaf.id,
    label: leafLabel(leaf),
    checked: leaf.id === activeLeaf ? true : undefined,
    onClick: () => navigate(leaf.href),
  }));
  return (
    <li>
      <Menu
        label={label}
        actions={actions}
        align="start"
        trigger={(props) => (
          <button
            type="button"
            {...props}
            {...tip.triggerProps}
            aria-label={label}
            className={clsx(
              "relative mx-auto flex size-11 items-center justify-center rounded-control transition-colors duration-150",
              active ? "bg-accent-soft text-accent" : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
            )}
          >
            <Icon size={20} aria-hidden />
          </button>
        )}
      />
      {tip.bubble}
    </li>
  );
}

/** A single-link rail entry (settings) with its tooltip. */
export function RailLink({ href, label, icon, active }: { href: string; label: string; icon: React.ReactNode; active: boolean }) {
  const tip = useTooltip(label, { side: "right" });
  return (
    <>
      <AppLink
        href={href}
        aria-label={label}
        aria-current={active ? "page" : undefined}
        {...tip.triggerProps}
        className={clsx(
          "mx-auto flex size-11 items-center justify-center rounded-control transition-colors duration-150",
          active ? "bg-accent-soft text-accent" : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
        )}
      >
        {icon}
      </AppLink>
      {tip.bubble}
    </>
  );
}

/** A rail entry that acts instead of navigating (expanding the sidebar). */
export function RailButton({ label, icon, onClick }: { label: string; icon: React.ReactNode; onClick: () => void }) {
  const tip = useTooltip(label, { side: "right" });
  return (
    <>
      <button
        type="button"
        aria-label={label}
        onClick={onClick}
        {...tip.triggerProps}
        className="mx-auto flex size-11 items-center justify-center rounded-control text-text-secondary transition-colors duration-150 hover:bg-surface-hover hover:text-text-primary"
      >
        {icon}
      </button>
      {tip.bubble}
    </>
  );
}

/** The inProjects.ai credit as the mark alone, for the collapsed rail. */
export function RailCredit() {
  const tip = useTooltip(t("builtBy.name"), { side: "right" });
  return (
    <>
      <a
        href={INPROJECTS_URL}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={t("builtBy.linkLabel")}
        {...tip.triggerProps}
        className="mx-auto flex size-11 items-center justify-center rounded-control transition-colors duration-150 hover:bg-surface-hover"
      >
        <InProjectsLogo height={18} markOnly />
      </a>
      {tip.bubble}
    </>
  );
}
