# ADR-0012: One navigation model for every signed-in page

**Status:** Superseded by ADR-0024 (2026-09-30). Accepted, 2026-09-25.
**Decision owners:** Owner.
**Scope:** `frontend/src/components/ViewerChrome.tsx`, `AppNav.tsx`,
`UserMenu.tsx`, `SidebarShell.tsx`, `AdminPage.tsx`, `PageHeader.tsx`,
`Button.tsx`, `frontend/src/lib/useSidebar.ts`, every view under
`frontend/src/views/`.

## Context

A visual audit (desktop 1440 px and mobile 390 px, both themes) found that
each screen solved navigation on its own:

- the left sidebar was global navigation on the home list, a document panel
  in the reader, and absent on projects and administration, where the logo
  was the only way back;
- breadcrumbs were flat (a project without "Projects", admin pages without
  "Administration", a project document without its project) and missing on
  the home page;
- sign out and the signed-in identity existed only on the home page;
- admin screens did not link to each other and each had its own eyebrow;
- buttons differed in height and font (serif fallback) between screens.

## Problem

Settle where global navigation lives, what the sidebar is for, and how the
same structure degrades to a phone, without two sidebars on one screen.

## Decision

Options considered:

1. **Primary navigation in the titlebar, sidebar = page context** (chosen).
   Sections in the navy bar from `lg`, in the account menu below. The
   sidebar always shows the current page's context (filters, document panel,
   file tree, diff files). About a day of work, no new data fetching.
2. **Global sidebar on every page.** Sections with filters and a project
   list on the left everywhere; the reader would need a second panel or hide
   one behind an icon. Heavier on mobile and needs list counts on every
   page (extra queries).

Rules that follow from option 1 are in `docs/DESIGN.md` section 4
("Navigation model"): section per page, breadcrumbs under the section with a
mobile-only root, one account menu, `SidebarShell` + `useSidebar()` with the
toggle in the titlebar, `AdminPage` tabs, `CenteredCard` brand for standalone
screens, `Button` and `PageHeader` for actions and headings.

## Reactivation trigger

A fourth top-level section, or a page that needs both global and contextual
navigation at once (then revisit option 2).

## Consequences

- Every signed-in page has the same way back, identity and sign out.
- The reader asks for the session itself (`useSessionUser`), because its
  route skips the app-level probe; a 401 only hides the account menu.
- The home sidebar no longer links to projects and admin pages; only the
  review-queue filter stays there.
- On phones the breadcrumb shows only the current location; parents are
  reachable through the account menu and the page panel.
