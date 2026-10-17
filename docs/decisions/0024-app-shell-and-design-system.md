# ADR-0024: App shell and design system v2

**Status:** Accepted, 2026-09-30. Supersedes ADR-0012.
**Decision owners:** Owner.
**Scope:** everything under `frontend/src/`; the contract is `docs/DESIGN.md`.

## Context

The interface grew screen by screen: a navy gradient bar with the section
links, a left sidebar that was global navigation on one page and a document
panel on another, a tall upload box above the document list, projects as
tall cards with two numbers, serif text in menus and forms, orange as the
colour of every link and focus ring, and a dozen local variants of buttons,
menus and inputs. The owner judged the result generic and hard to use and
wrote a new design contract (`docs/DESIGN.md`, version 2.1).

## Problem

Rebuild every screen on one structure without changing permissions, API
calls or document handling, and choose how the contract maps onto the
existing React/Vite/Tailwind 4 code.

## Decision

1. **One shell, mounted once.** `components/shell/AppShell` wraps every
   signed-in route in `App.tsx` at the same tree position, so the sidebar,
   its scroll and folded groups survive navigation. The reader and share
   views render inside the same element with `me = null` until the session
   is known; children never remount when the chrome appears. Pages declare
   their breadcrumb with `PageContext` (a portal into the shell's slot) and
   their width with `Page`.
2. **Navigation lives in the sidebar only.** Documents (All, Mine, Shared
   with me, Favourites), Projects (the five most recently opened, then all)
   and Administration for admins. 256 px expanded or a 64 px rail by a
   remembered preference on desktop, the rail on tablets, a drawer on phones.
   The global bar holds search (command palette, Cmd/Ctrl+K), the inbox and
   the account menu with theme and language.
3. **Scope and filters are separate.** The sidebar picks the scope of the
   document list (`?f=state:mine` and friends, old links keep working);
   kind, sharing, source, project, doc type, freshness and tags are toolbar
   filters that combine (OR within a kind, AND across kinds). The reference
   mock-up showed kinds and states in the sidebar; the contract (section 7)
   wins.
4. **Tokens are the only palette.** `styles/theme.css` switches off the stock
   Tailwind colours, sizes, radii and shadows, so a stray `bg-blue-500`
   renders nothing, and `styles/designTokens.test.ts` names it. Old token
   names (`paper`, `ink`, `rule`, `navy`, `font-display`) were migrated, not
   aliased. Theme preference is `light`, `dark` or `system`, resolved before
   first paint by `index.html`.
5. **Typography.** The UI uses the platform face; Source Serif 4 is only for
   document prose, JetBrains Mono for code. Both are self-hosted
   (`styles/fonts.css`, Latin and Latin Extended subsets only, to stay inside
   the 10 MiB bundle budget); Mona Sans and the Google Fonts request are gone.
6. **One component per pattern.** `components/ui/` holds the primitives. A
   `MenuAction` list is rendered as the dropdown on wider screens and the
   bottom sheet on phones, so an action cannot exist in one and not the
   other; document rows, the reader's `…` menu and the phone sheet share
   `buildAssetMenuActions`.
7. **Reader.** The document takes the page. One toolbar (edit, share, focus
   mode, inspector, `…`) and one inspector with Files (collections), Contents,
   Details and History: docked at 1280 px and wider, a drawer below. The
   inspector starts closed, a collection opens on its files, a user's choice
   is remembered per kind. The old left management panel is gone.
8. **Motion.** Anime.js 4 through its WAAPI module, only in `lib/motion.ts`
   (menus, dialogs, drawers, sheets, sidebar tree, badge bump), transform and
   opacity only, skipped under `prefers-reduced-motion` and without WAAPI,
   never awaited by state changes.

### Options considered

| Option | Cost | Outcome |
| --- | --- | --- |
| Reskin the existing components | Low | Keeps two navigations and the panel sprawl the contract forbids |
| New UI framework (shadcn, Radix) | Medium, new dependencies | Contract asks to reuse what exists; not needed for the primitives used |
| **Own shell and primitives on the current stack** | High, one pass over every screen | One model everywhere, no new framework, Anime.js as the only addition |

## Reactivation trigger

Revisit when a screen needs a pattern the primitives cannot express (for
example bulk selection in admin tables), or when the bundle budget forces a
different font strategy.

## Consequences

- `ViewerChrome`, `AppNav`, `UserMenu`, `SidebarShell`, `SidebarNav`,
  `CollectionLayout`, `AssetRow`, `AssetList`, `UploadCard`, `UploadStrip`,
  `AssetToolbar`, `useViewerToolbar`, `useSidebar`, `MenuButton`, the old
  `Modal`, `Button` and `PageHeader`, `BackgroundGraph` and
  `EditableProjectHeader` were removed.
- A new page renders `PageContext` and `Page`, uses `components/ui/`, and
  adds its routes to `navModel` only when they are navigation.
- Uploads start from one "Upload" action (dialog with the audience choice)
  or a drag over the page; there is no permanent drop zone.
- Admin screens have no tab strip; the sidebar links them.
