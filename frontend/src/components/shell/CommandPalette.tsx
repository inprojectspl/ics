import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import {
  ArrowRight,
  Bell,
  FilePlus2,
  FileText,
  FolderKanban,
  FolderPlus,
  Moon,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { type AssetSummary, type Me, type ProjectSummary } from "../../api";
import { t, type MessageKey } from "../../lib/i18n";
import { useEnterMotion } from "../../lib/motion";
import { navigate } from "../../lib/navigate";
import { projectListQuery } from "../../lib/queries";
import { setThemePreference, useTheme } from "../../lib/theme";
import { useDocumentSearch } from "../../lib/useDocumentSearch";
import { Kbd } from "../ui/Kbd";
import { kindIcon } from "../documents/kindIcon";
import { trapTab } from "../ui/floating";
import { useOverlay } from "../ui/useOverlay";
import { matchesText } from "../../lib/text";

interface Command {
  id: string;
  group: MessageKey;
  label: string;
  hint?: string;
  icon: LucideIcon;
  run: () => void;
}

const NO_PROJECTS: ProjectSummary[] = [];
const MAX_PER_GROUP = 6;

function useCommands(me: Me, query: string): { commands: Command[]; searching: boolean; failed: boolean } {
  const q = query.trim().toLowerCase();
  const theme = useTheme();
  const projects =
    useQuery({
      ...projectListQuery,
    }).data ?? NO_PROJECTS;
  const docs = useDocumentSearch(query, MAX_PER_GROUP);

  const commands = useMemo(() => {
    const out: Command[] = [];
    const hit = (label: string) => matchesText(label, q);

    const found: AssetSummary[] = docs.data ?? [];
    for (const a of found.slice(0, MAX_PER_GROUP)) {
      out.push({
        id: `doc:${a.slug}`,
        group: "palette.documents",
        label: a.title ?? a.slug,
        hint: a.summary ?? undefined,
        icon: kindIcon(a.kind),
        run: () => navigate(`/v/${a.slug}`),
      });
    }
    for (const p of projects.filter((p) => hit(p.name)).slice(0, q ? MAX_PER_GROUP : 4)) {
      out.push({
        id: `project:${p.slug}`,
        group: "palette.projects",
        label: p.name,
        icon: FolderKanban,
        run: () => navigate(`/projects/${p.slug}`),
      });
    }
    const actions: Array<Omit<Command, "group">> = [
      { id: "act:upload", label: t("palette.upload"), icon: FilePlus2, run: () => navigate("/?add=upload") },
      { id: "act:project", label: t("palette.newProject"), icon: FolderPlus, run: () => navigate("/projects?new=1") },
      {
        id: "act:theme",
        label: t(theme === "dark" ? "theme.toLight" : "theme.toDark"),
        icon: theme === "dark" ? Sun : Moon,
        run: () => setThemePreference(theme === "dark" ? "light" : "dark"),
      },
    ];
    for (const a of actions.filter((a) => hit(a.label))) out.push({ ...a, group: "palette.actions" });
    const places: Array<Omit<Command, "group">> = [
      { id: "go:docs", label: t("nav.documents"), icon: FileText, run: () => navigate("/") },
      { id: "go:projects", label: t("nav.projects"), icon: FolderKanban, run: () => navigate("/projects") },
      { id: "go:notifications", label: t("notifications.title"), icon: Bell, run: () => navigate("/notifications") },
      { id: "go:settings", label: t("account.menu"), icon: Settings, run: () => navigate("/account/notifications") },
      ...(me.role === "admin"
        ? [{ id: "go:admin", label: t("nav.admin"), icon: ShieldCheck, run: () => navigate("/admin/users") }]
        : []),
    ];
    for (const p of places.filter((p) => hit(p.label))) out.push({ ...p, group: "palette.goTo" });
    return out;
  }, [q, docs.data, projects, theme, me.role]);

  return { commands, searching: docs.isSearching, failed: Boolean(docs.error) };
}

interface Props {
  me: Me;
  open: boolean;
  onClose: () => void;
}

/**
 * Global search and commands (Cmd/Ctrl+K): documents by full-text search,
 * projects, places and a few actions, all from the keyboard. A combobox:
 * focus stays in the field, arrows move the highlighted option.
 */
export function CommandPalette({ me, open, onClose }: Props) {
  if (!open) return null;
  return <PaletteDialog me={me} onClose={onClose} />;
}

function PaletteDialog({ me, onClose }: { me: Me; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  useOverlay(panelRef, true, { onClose, modal: true, initialFocus: inputRef });
  useEnterMotion(panelRef, "dialog");
  const { commands, searching, failed } = useCommands(me, query);
  const active = Math.min(cursor, Math.max(0, commands.length - 1));

  useEffect(() => {
    document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, listId]);

  const run = (c: Command | undefined) => {
    if (!c) return;
    onClose();
    c.run();
  };

  let lastGroup: MessageKey | null = null;
  const rows: ReactNode[] = [];
  commands.forEach((c, i) => {
    if (c.group !== lastGroup) {
      lastGroup = c.group;
      rows.push(
        <li key={`h:${c.group}`} role="presentation" className="px-3 pb-1 pt-3 text-meta font-medium text-text-secondary first:pt-1">
          {t(c.group)}
        </li>,
      );
    }
    rows.push(
      <li
        key={c.id}
        id={`${listId}-${i}`}
        role="option"
        aria-selected={i === active}
        onPointerMove={() => setCursor(i)}
        onClick={() => run(c)}
        className={clsx(
          "mx-1.5 flex cursor-pointer items-center gap-3 rounded-control px-2.5 py-2",
          i === active ? "bg-accent-soft" : undefined,
        )}
      >
        <c.icon size={16} aria-hidden className={i === active ? "shrink-0 text-accent" : "shrink-0 text-text-secondary"} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-ui text-text-primary">{c.label}</span>
          {c.hint && <span className="block truncate text-meta text-text-secondary">{c.hint}</span>}
        </span>
        {i === active && <ArrowRight size={14} aria-hidden className="shrink-0 text-accent" />}
      </li>,
    );
  });

  return createPortal(
    <div className="fixed inset-0 z-[65] flex items-start justify-center px-3 pt-[max(1rem,10vh)]" role="presentation">
      <div aria-hidden onClick={onClose} className="absolute inset-0 bg-scrim" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={t("palette.title")}
        onKeyDown={(e) => trapTab(e, panelRef.current)}
        className="relative flex max-h-[min(34rem,80dvh)] w-full max-w-xl flex-col overflow-hidden rounded-overlay border border-border bg-surface shadow-floating"
      >
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          <Search size={18} aria-hidden className="shrink-0 text-text-secondary" />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded
            aria-controls={listId}
            aria-activedescendant={commands.length ? `${listId}-${active}` : undefined}
            aria-autocomplete="list"
            aria-label={t("palette.title")}
            placeholder={t("palette.placeholder")}
            maxLength={200}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setCursor(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") setCursor((c) => Math.min(c + 1, commands.length - 1));
              else if (e.key === "ArrowUp") setCursor((c) => Math.max(c - 1, 0));
              else if (e.key === "Enter") run(commands[active]);
              else return;
              e.preventDefault();
            }}
            className="h-13 min-w-0 flex-1 bg-transparent text-body text-text-primary outline-none placeholder:text-text-tertiary focus-visible:outline-none"
          />
          {searching && <span className="text-meta text-text-secondary">{t("palette.searching")}</span>}
        </div>
        {failed && <p role="alert" className="px-4 py-3 text-ui text-text-secondary">{t("home.searchFailed")}</p>}
        <ul id={listId} role="listbox" aria-label={t("palette.results")} className="min-h-0 flex-1 overflow-y-auto py-1.5">
          {rows.length ? rows : !failed && (
            <li role="presentation" className="px-4 py-8 text-center text-ui text-text-secondary">
              {t(searching ? "palette.searching" : "palette.empty")}
            </li>
          )}
        </ul>
        <div className="hidden items-center gap-4 border-t border-border px-4 py-2 text-meta text-text-secondary sm:flex">
          <span><Kbd>↑</Kbd> <Kbd>↓</Kbd> {t("palette.hintMove")}</span>
          <span><Kbd>Enter</Kbd> {t("palette.hintOpen")}</span>
          <span><Kbd>Esc</Kbd> {t("palette.hintClose")}</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
