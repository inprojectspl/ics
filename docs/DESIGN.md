# ICS - Design & UX contract

Status: binding design contract · Version 2.1 · 2026-09-30 · Implementation decisions: ADR-0024  
**Product:** ICS (Internal Content Sharing System) · **Frontend:** React + TypeScript + Vite + Tailwind CSS 4 (`@tailwindcss/vite`)

> **Goal:** ICS is to be a calm, polished application for working with documents and projects: visually close to the quality of native Apple applications, functionally as well organised as good administration consoles (Cloudflare among others), but without copying their look. **The content and the user's task always take precedence over navigation and decoration.**
>
> This document **replaces the previous visual contract**, in particular the requirement for a navy gradient bar, an orange accent on all interactions, primary navigation in the top bar, a contextual sidebar as the only sidebar, and large single-column cards as the mandatory presentation of every list. Existing decisions on security, permissions, business logic, document formats and the API remain in force.

## 0. Overriding principles (MUST)

1. **Content-first.** The largest, most prominent area of the screen goes to its main function: in "Documents", the documents; in "Projects", the projects; in the reader, the document content; in "Administration", the administrative data and operations.
2. **One shell.** Every authenticated page uses **one** `AppShell` skeleton: a collapsible left sidebar + a light global bar + an optional, lower context bar + a work area. We do not build parallel layouts for Documents, Projects and Administration.
3. **One global navigation.** The main sections and their trees are in the sidebar. The top bar **does not repeat** the "Documents / Projects / Administration" buttons. Breadcrumbs are for orientation, not a second menu.
4. **One place for actions.** Actions that belong to a screen are gathered in **one consistent toolbar** (or a `…` menu), instead of scattering toggles across the header, the content and several panels.
5. **Progressive disclosure.** The most frequently used operations are visible first. Rare and advanced options go into labelled menus/panels. However, we do not hide critical functions behind a hover gesture alone.
6. **Responsive ≠ a shrunken desktop.** On a phone, navigation becomes a drawer, tools are grouped, list structures change format, and reading does not require horizontal scrolling of the page.
7. **One component, one pattern.** The same functions have the same look and behaviour. Reusability applies to **components, action data and patterns**, not to artificially merging different actions into one unreadable all-in-one control.
8. **Typography has roles.** The whole UI is set in a sans-serif typeface; the serif typeface is used **only for long document content**. We do not use serif type in menus, project descriptions, filters, forms or card metadata.
9. **Accessibility is a product feature.** We design for WCAG 2.2 AA: contrast, keyboard, focus, touch, zoom, system preferences, error states and no reliance on colour alone.
10. **Fix the structure first, then the cosmetics.** No amount of shadows, rounded corners and animations justifies a gigantic upload box pushing the list down, five control bars, or empty cards with a single line of information.
11. **Subtle motion with Anime.js.** Anime.js is the preferred library for deliberate interface animations. Motion should feel pleasant and communicate a change of state, but it must **never delay navigation, capture interactions or compete with the content**. The interface must remain fully usable without animation.

The words **MUST / MUST NOT / SHOULD / MAY** are normative: required, forbidden, preferred and optional respectively.

---

## 1. Starting point and goal of the redesign

Based on the supplied screens and the previous contract:

| Current problem | Required result |
| --- | --- |
| Dark, dominant navbar with global navigation, language, theme and profile | A light application bar: global search, user menu, possibly one global shortcut; navigation moves to the sidebar |
| The documents sidebar serves almost exclusively for filters, and other screens do not use it | One **persistent/collapsible sidebar** with a tree of modules, projects and views; filters as part of the view, not a separate global sidebar |
| A huge upload dropzone takes the most important part of the Documents screen | A compact **Add / Upload** button, with the dropzone opened on demand or during drag-and-drop; the list is visible immediately |
| Projects as very tall full-width cards, little data on screen | A concise project list with a clear hierarchy, counters and role; a useful number of items without scrolling the whole screen |
| The same information appears in the navbar, the title and the cards | Distinct roles for the layers: global context, path, a single view header, the actual data |
| Very wide empty margins around a narrow working column | Width depends on the type of work: lists and tables use the area, the reader has a deliberately chosen text measure |
| Controls carry similar visual weight to the data | A clear separation: **primary content > primary action > context > secondary controls** |

**Aesthetic direction:** light, neutral surfaces; precise alignment; a calm blue for interaction; a subtle ICS signature; sparing shadows; considered density. **Forbidden:** full-screen gradients, glass cards, decorative bento, loud indicators, excessively rounded containers and "a dashboard from a template generator".

---

## 2. Information architecture: one navigation model

### 2.1. Main layout

```text
┌───────────────────────────────────────────────────────────────────────────┐
│ APP TOPBAR   [☰]  ICS / workspace        [⌕ Search… ⌘K]          [Avatar] │ 56 px
├───────────────────────────────────────────────────────────────────────────┤
│ CONTEXT BAR  Documents / All                [optional context]            │ 40 px
├───────────────┬───────────────────────────────────────────────────────────┤
│ SIDEBAR       │ PAGE HEADER   Documents       [Toolbar: + Add | …]        │
│               │                                                           │
│ ▾ Documents   │ PRIMARY CONTENT                                           │
│   All         │ list, results grid, file tree or reader                   │
│   Mine        │                                                           │
│   Shared      │                                                           │
│ ▾ Projects    │                                                           │
│   All         │                                                           │
│   Benin Legit │                                                           │
│   UKE         │                                                           │
│ ▸ Admin*      │                                                           │
│               │                                                           │
│ [⚙ Settings]  │                                                           │
└───────────────┴───────────────────────────────────────────────────────────┘
* Visibility follows actual permissions.
```

The diagram above shows **responsibilities**; it does not impose an extra row of tools on every page. If the context bar adds no information (for example on a section's main screen), it can be hidden. The document view can enable **focus mode**, hiding the sidebar and non-critical tools.

### 2.2. Sidebar (`AppSidebar`)

- **Desktop from 1024 px:** expanded by default, width **256 px**; collapsed **64 px**. The user toggles it with an always visible button with an icon and an accessible name (`Collapse menu` / `Expand menu`). We store the preference locally, separately from the expansion of sections.
- **Tablet 768-1023 px:** collapsed to **64 px** by default; it can be expanded as an overlay or on demand, without squeezing the data into an unreadable column.
- **Phone <768 px:** the sidebar is a **drawer**, closed by default, opened with an unambiguous menu icon; closed with `×`, Escape, choosing a route and clicking the backdrop. On opening, focus moves into the drawer; on closing, it returns to the button that opened it.
- The sidebar contains **one scrollable tree** and a fixed, small bottom section. No second, parallel left sidebar appears on routes.
- When collapsed, the icons remain legible, the selected section has a clear active state, and the icons offer a tooltip on hover/focus. A section's children may be available through an **accessible flyout**, but never through hover alone.
- **Expanding is obvious:** a chevron next to the group (`chevron-right` → `chevron-down`), separate from the navigation link. Avoid a situation where clicking the name unpredictably sometimes navigates to a page and sometimes expands the group.
- At most **three levels of legible navigation** (module → view/project → subsection). Deeper data structures stay in the main file browser/tree inside the view.
- Active state: a soft background + a position marker + legible text; do not rely for this information on a thin coloured bar alone.
- Counters are optional, muted and appear only when they genuinely help. We do not show totals next to every branch if that turns into a board of digits.

**Example sections (data/roles decide the actual items):**

```text
Documents
  All
  Mine
  Shared with me
  Favourites (if the feature exists)
Projects
  All projects
  [pinned/recently used projects, limited number]
  See all
Administration [authorised users only]
  Users
  Review / moderation
  CDN
  Audit
```

**Forbidden:** permanently rendering dozens of projects in the sidebar. A long tree has a limit of visible items, a search, or an option to go to the full view.

### 2.3. Two-level top bar

**`AppTopbar`: global, 56 px**:

- Left side: sidebar toggle, a subtle ICS logo/name; if the sidebar is expanded, we do not duplicate a large logotype in the bar.
- Centre (if the width allows): **global search** with the hint `⌘K` / `Ctrl+K`, a shared command palette for documents, projects and available actions.
- Right side: at most **one truly global action**, possibly search as an icon on the phone, and an avatar that opens the user menu. Language, theme and sign-out live in the account menu/settings, not as permanently visible buttons.
- No full-width navy gradient. The surface is light/dark according to the theme, with a delicate bottom line. `backdrop-blur` only possibly for a sticky bar, provided contrast is preserved; the content stays opaque.

**`ContextBar`: contextual, ~40 px**:

- Breadcrumbs for routes with a hierarchy: e.g. `Projects / Benin Legit / Documents / ...`.
- On the right, at most a small set of **location-specific** actions that are not already in the toolbar; by default no extra actions.
- On the phone: a shortened path (`‹ Projects` + the current context), long names truncated semantically, never pushing the layout sideways.
- It does not duplicate the large page title or add extra global tabs.

### 2.4. Control hierarchy

Each screen may have **at most**:

1. the global application bar,
2. the context bar, **only when it is needed**,
3. **one** view header with its associated toolbar,
4. the actual data.

Sections such as "Details / Versions / Access" may use local tabs **inside the content of a specific object**. Tabs must not replace the navigation tree and breadcrumbs in parallel. A function present in a panel does not automatically get a second button in the navbar.

---

## 3. Layout, space and density

| Element | Reference parameter | Rule |
| --- | --- | --- |
| AppTopbar | 56 px | shared by all authenticated routes |
| ContextBar | 40 px | can be hidden, no empty row |
| Sidebar expanded / collapsed | 256 / 64 px | persistent desktop preference |
| Desktop work margin | 24-32 px | narrower on smaller screens |
| Mobile work margin | 16 px (minimum 12 px at 320 px) | accounts for the safe area |
| Rhythm | 4 px scale, default spacing 8/12/16/24/32 | no random `gap` and `padding` |
| List row compact / comfortable | approximately 56 / 68 px | optional density, not a random growth of cards |
| Toolbar | approximately 40 px + 32-36 px controls | in one group with the header |
| Data area | 100% of the available width, a sensible limit e.g. 1480 px | we do not narrow project lists to an article column |
| Document reader | **maximum content space 1100 px** | keeps the owner's existing preference; details in §8 |

- White space **groups**; it does not separate the user from the work: more air between sections, less empty height inside repeated rows.
- Do not wrap **every** piece of UI in a card. A table/list can be a single shared container with subtle separators.
- One visual level does not get three outlines: *a card in a card in a panel* is an anti-pattern.
- On large screens, legible data density matters more than a gigantic empty margin on the right. The width of the main content is chosen **per view type**, not with one global `max-w-4xl`.
- Long headings and names must have `min-w-0`, correct `overflow-wrap` and an appropriate height. In a list, use at most 2 lines of the name + a tooltip/full name in the details view, without truncating critical content.
- Scrolling should belong to a predictable area: the sidebar scrolls its navigation; the content scrolls independently if the shell requires it; avoid unintended nested scrolls.
- `min-h-0` for flex/grid scroll containers, `100dvh` / `h-dvh` for full-screen and mobile views; take `env(safe-area-inset-*)` into account.

---

## 4. Colour: cool neutrality, functional accent

**The new direction replaces the previous "warm cream + orange + navy" set.** We keep the orange ICS mark/logo as a **small element of identity**. We do not turn it into a parallel colour for CTAs and links. The functional UI accent is a **muted blue** (system-like, calm, legible). Status colours are used for semantics only.

### 4.1. Tokens: light variant (starting point for the audit)

| Role | Tailwind v4 token | Value |
| --- | --- | --- |
| Application background | `canvas` | `#F5F7FA` |
| Main surface / reader / card | `surface` | `#FFFFFF` |
| Subtle fill / grouping | `surface-subtle` | `#F0F3F7` |
| Hover / selected neutral element | `surface-hover` | `#E9EFF6` |
| Separator | `border` | `#DCE3EC` |
| Strong separator / input border | `border-strong` | `#C6D0DC` |
| Primary text | `text-primary` | `#182332` |
| Secondary text | `text-secondary` | `#4B5B70` |
| Weaker text (not for key labels) | `text-tertiary` | `#64748B` |
| Action/link/focus | `accent` | `#1769D2` |
| Action on hover | `accent-hover` | `#145CB8` |
| Soft selection | `accent-soft` | `#E8F2FF` |
| Text on accent | `on-accent` | `#FFFFFF` |
| ICS mark signature (not a CTA) | `brand-mark` | `#FF5500` |
| Success | `success` | `#147D59` |
| Warning | `warning` | `#946200` |
| Error/deletion | `danger` | `#B42332` |

**Contrast note:** `text-tertiary` is only for less important metadata on a white surface; on `canvas` and for important labels use at least `text-secondary`. No "nice light grey" labels justify insufficient contrast.

### 4.2. Tokens: dark mode

| Role | Value |
| --- | --- |
| `canvas` | `#101419` |
| `surface` | `#181F28` |
| `surface-subtle` | `#202A36` |
| `surface-hover` | `#263243` |
| `border` | `#323F51` |
| `border-strong` | `#405269` |
| `text-primary` | `#F4F7FB` |
| `text-secondary` | `#B7C3D2` |
| `text-tertiary` | `#A8B5C4` |
| `accent` | `#8ABBFF` |
| `accent-hover` | `#A6CAFF` |
| `accent-soft` | `#193451` |
| `on-accent` | `#071929` |
| `brand-mark` | `#FF5500` |
| `success` | `#5AD6A0` |
| `warning` | `#F3BF65` |
| `danger` | `#FF8B93` |

- We support `system`, `light` and `dark` (including switching without flicker on initialisation). The theme setting is in the account menu/settings.
- Statuses are recognisable **by text and icon**, not by colour alone.
- State backgrounds (`*-soft`) are added as explicit tokens only when they are needed, keeping adequate contrast in both themes.
- **Do not use** gradients for ordinary surfaces, full-screen glows or multicoloured card backgrounds by file type.

### 4.3. Tailwind CSS 4: one source of truth

`src/styles/theme.css` remains the **canonical place** for defining the palette and base rules. An example of the intended start of the file (to be completed with the full set from the tables above):

```css
@import "tailwindcss";

@theme {
  --color-canvas: #F5F7FA;
  --color-surface: #FFFFFF;
  --color-surface-subtle: #F0F3F7;
  --color-surface-hover: #E9EFF6;
  --color-border: #DCE3EC;
  --color-border-strong: #C6D0DC;
  --color-text-primary: #182332;
  --color-text-secondary: #4B5B70;
  --color-text-tertiary: #64748B;
  --color-accent: #1769D2;
  --color-accent-hover: #145CB8;
  --color-accent-soft: #E8F2FF;
  --color-on-accent: #FFFFFF;
  --color-brand-mark: #FF5500;
  --color-success: #147D59;
  --color-warning: #946200;
  --color-danger: #B42332;

  --radius-control: 10px;
  --radius-card: 14px;
  --radius-overlay: 18px;
  --shadow-card: 0 1px 2px rgb(24 35 50 / 0.035);
  --shadow-floating: 0 12px 36px rgb(24 35 50 / 0.14);
  --font-ui: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, Arial, sans-serif;
  --font-reading: "Source Serif 4", Georgia, serif;
  --font-code: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}

:root { color-scheme: light; }

[data-theme="dark"] {
  color-scheme: dark;
  --color-canvas: #101419;
  --color-surface: #181F28;
  --color-surface-subtle: #202A36;
  --color-surface-hover: #263243;
  --color-border: #323F51;
  --color-border-strong: #405269;
  --color-text-primary: #F4F7FB;
  --color-text-secondary: #B7C3D2;
  --color-text-tertiary: #A8B5C4;
  --color-accent: #8ABBFF;
  --color-accent-hover: #A6CAFF;
  --color-accent-soft: #193451;
  --color-on-accent: #071929;
  --color-brand-mark: #FF5500;
  --color-success: #5AD6A0;
  --color-warning: #F3BF65;
  --color-danger: #FF8B93;
  --shadow-card: 0 1px 2px rgb(0 0 0 / 0.14);
  --shadow-floating: 0 16px 44px rgb(0 0 0 / 0.38);
}

@layer base {
  html { font-family: var(--font-ui); }
  body { background: var(--color-canvas); color: var(--color-text-primary); }
  :where(button, a, input, textarea, select, [tabindex]):focus-visible {
    outline: 2px solid var(--color-accent);
    outline-offset: 2px;
  }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

**Important:** this is an example of tokens, **not an instruction to overwrite the whole** existing `theme.css`; keep the Markdown renderer styles and existing application features that are needed, and remove outdated rules after the migration. In Tailwind 4, utility classes are to use the tokens, e.g. `bg-canvas`, `bg-surface`, `text-text-primary`, `border-border`, `rounded-control`, `font-reading`. The `text-text-*` names are deliberately unambiguous: `text` is the colour role, not the font size.

**MUST NOT:** incidental `bg-blue-500`, `text-slate-500`, `bg-[#...]`, inline styles with hex values, adding new global CSS on every page. Raw palette values appear only in `theme.css` and possibly in the token test file.

---

## 5. Typography: native UI + editorial reading

### 5.1. Families

| Context | Family | Reason |
| --- | --- | --- |
| Navigation, dashboard, page headings, project descriptions, forms, tables, toasts | `font-ui`: the system `-apple-system / BlinkMacSystemFont / Segoe UI` with fallbacks | natural rendering on macOS/iOS and a legible, native look on other systems |
| Markdown and document prose | `font-reading`: **Source Serif 4** (fallback Georgia) | a refined text typeface, good legibility in long paragraphs, variable optical sizing |
| Code, pre fragments, identifiers that need a fixed width | `font-code`: **JetBrains Mono** | precise distinction of code and technical data |

- **Do not use serif in the UI**. The project title and description, the document summary in a list and the dropzone text are sans-serif. Serif applies only in the **reader content** (plus a quoted source, when preserving the original formatting is required).
- For numbers in tables, primarily use `font-variant-numeric: tabular-nums`; do not switch whole columns to monospace without a reason; monospace is appropriate for code, hashes and identifiers.
- Prefer self-hosting Source Serif 4/JetBrains Mono (licences, and preloading only the weights in use) over depending on many external font requests. Do not distribute the Apple system font as a file.

### 5.2. Scale and legibility

| Usage | Size / line-height | Weight |
| --- | --- | --- |
| Main section name | `clamp(24px, 2vw, 32px)` / 1.2 | 650-700 if the typeface supports it; otherwise 600 |
| View/details title | 20-24 px / 1.3 | 600 |
| List item title | 14-16 px / 1.4 | 600 |
| Base UI | **14-15 px** / 1.45-1.55 | 400-500 |
| Secondary metadata | 12-13 px / 1.4 | 400-500 |
| Document content (desktop) | **18 px** / **1.65-1.75** | 400 |
| Document content (mobile) | **16-17 px** / 1.6-1.7 | 400 |
| Code in a document | 13-14 px / 1.55 | 400 |

- The table is a directional specification; implement the exact values as **named typography tokens / central styles**, not as individual `text-[...]` on every screen.
- Hierarchy should come from **weight, size and layout**, not from ten shades of grey and small caps.
- Avoid full UPPERCASE in the UI; exception: short technical labels and existing proprietary markings.
- `text-wrap: balance` for headings; `text-wrap: pretty` for prose as progressive enhancement; no forced breaking of words in the middle.
- **Zoom up to 200%** and text enlargement must not break the flow of pages. Avoid fixed heights that contain growing text.

---

## 6. Shared component library

We do not require installing a new UI framework. First check what exists in the repo, then refactor. Accessible headless primitives are allowed if the repo already uses them or a concrete need is demonstrated; the look always comes from our tokens.

| Component / pattern | Single responsibility | Guidance |
| --- | --- | --- |
| `AppShell` | shared application layout | topbar, contextbar, sidebar, main, responsive handling |
| `AppSidebar` | main navigation tree | collapsed/expanded/drawer + persistence |
| `SidebarGroup` / `SidebarItem` | tree levels | icon, label, chevron, active/expanded |
| `AppTopbar` | global tools | search/command palette, account |
| `ContextBar` / `Breadcrumbs` | orientation in the hierarchy | breadcrumbs, shortcuts for mobile |
| `PageHeader` | a single view title | title, optionally a short explanation |
| `PageToolbar` | view actions and controls | CTA, search in view, filters, sort, view switch, `…` menu |
| `Button`, `IconButton` | interactions | primary/secondary/ghost/danger, loading, disabled, focus |
| `Menu`, `Dropdown`, `ActionSheet` | grouped actions | **shared action model**, different form on desktop/mobile |
| `DataList`, `DataRow`, `DataTable` | dense presentation of collections | shared selection/hover/keyboard, without a monolithic "does everything" component |
| `Panel`, `Disclosure`, `Drawer`, `Dialog` | collapsible details | recognisable trigger and state; focus control |
| `SearchField`, `FilterPopover`, `SortMenu` | shared search and filtering | one pattern across all lists |
| `EmptyState`, `ErrorState`, `Skeleton` | complete asynchronous states | zero layout shift, retry, precise messages |
| `Badge`, `StatusIndicator`, `Tooltip` | semantic information | label + possibly an icon, not colour alone |
| `DocumentSurface`, `ReaderToolbar`, `DocumentOutline` | reading | separated from the app chrome |

**Sharing rules:**

- Extract a component when **the same interaction pattern** appears twice or reuse is certain; three repetitions of identical UI are an architectural error.
- Avoid a `UniversalPage` with dozens of flags (`isDocument`, `isProject`, `showSidebar2`, etc.). A shared *skeleton and elements* + small domain specialisations is the correct solution.
- An action definition (`id`, `label`, `icon`, `permission`, `disabled`, `destructive`, `handler`) should be one for the inline variant, the menu and the mobile sheet. Two independent sets of actions lead to functions drifting apart.
- Do not create yet another variant of a dialog, toast, input, menu or button in a page file.
- **Visual reuse must not change meaning.** "Delete", "Versions" and "Share" remain separate, labelled actions even when they fit in a single action menu.

### 6.1. Buttons and actions

- In a single area, by default **one** highlighted CTA (`primary`). The rest are `secondary`/`ghost`/menu.
- "Documents" example: `+ Add document` (primary); local search; filtering; sort; `…` for the remaining actions.
- "Projects" example: `+ New project` (primary); search; sort/filter; no dedicated large button in a separate corner of the screen.
- The order and labels of actions repeat across similar views. Keep the system's functional terminology (`Upload`, `New project`, `Share`, `Version history`).
- Icons 16-20 px, one family (the existing Lucide preferred). An icon alone **is not enough** when its meaning is not obvious; use a label or a tooltip + an accessible name.
- Touch: a target of **at least 44 × 44 CSS px**, even when the visual glyph is smaller. In tight tables use a larger clickable area or a row menu.

### 6.2. Cards, lists, dialogs

- Radius: control **10 px**, card **14 px**, overlay/dialog **18 px**; no random `rounded-3xl`.
- Ordinary lists: subtle separators, a slight hover fill; **no lifting every item with a shadow**. Reserve shadows for true overlays.
- On a card, each piece of information has a clear place: name, 1 line of context, metadata; no huge padding around 12 words.
- Dialogs serve specific decisions/edits; they do not become a second dashboard. Complex multi-step work gets a full view/drawer of an appropriate width.
- Destructive actions have clear names and adequate confirmation; not all of them require the same excessive modal.

---

## 7. The "Documents" screen: documents at first glance

**User goal:** find, open, upload, organise and share a document.

**Desktop visual order:**

1. One `PageHeader` ("Documents", possibly the number of results as helper text).
2. One `PageToolbar`: `+ Add` and search/filter/sort/view as needed.
3. **An immediately visible list** of documents or a collection.

**Upload:**

- By default **do not render a tall dropzone before the list**.
- Clicking `+ Add` opens a small menu: `Upload files`, `New collection`, `Import folder / HTML bundle` (existing capabilities only). Next, a dialog/drawer with a proper dropzone and the publication mode (`Org SSO / Public`) in **one logical step**.
- While files are dragged over the main view, a discreet full-area drop target appears; it disappears on drag-leave. It **does not capture text dragging** and does not permanently change the layout. `input[type=file]` stays available without drag-and-drop.
- Do not mix the "publication mode" with the global list filters. The mode applies to **the content being published**, not to the whole page.

**List:**

- By default a **compact row view** suited to scanning titles; another view form may be available if it corresponds to an existing function and is justified.
- Row: type icon, title (max. 2 lines), owner / project (space permitting), update time, sharing status, `…`. Metadata is important, but smaller than the name.
- Document kinds and states (Markdown, PDF, HTML bundle, collection, versions, GitLab sync, public/protected) share **a common system of icons/labels**, not unique coloured frames around whole rows.
- Clicking the name/main area opens the document. `Rename` is a separate, unambiguous action; do not turn a title click into editing.
- In the desktop view `…` may stay permanently visible as a discreet affordance; less important icons may be shown on hover **only on devices that actually support hover**. Access to all operations via keyboard and touch must remain complete.
- The item count, sort and filter work together; an active filter is recognisable, it can be removed, and `Clear filters` does not require going to the sidebar.

**Sidebar in Documents:** only global navigation and possibly contextual shortcuts/nested views **within the same structure**; types/state/source should be filters in a toolbar popover, not an independent fixed column with a counter next to each item.

---

## 8. Document reader: reading is the product

**Goal:** a long document can be read comfortably, a passage found, the structure previewed, and versions and sharing handled without fighting the UI.

- The content takes the **main surface**. The app shell stays light; in `Focus / Reading` one button hides the sidebar and optionally the contextual chrome. The button has a clear state and the text/tooltip `Focus mode` / `Exit focus mode`.
- The default document space may be **up to 1100 px**, in line with the previously adopted preference for a wide editorial surface. **Do not automatically shrink the whole container to 44rem.** Long paragraphs may get an **optional "Narrower text" mode** (e.g. 75-85 `ch`) in the reader settings, but not as a forced new default. Tables, images, code blocks and diagrams use the full available container width.
- The document `h1` title is rendered **once**. If the file starts with an `h1`, do not display a second gigantic title above it; the resource name is in the breadcrumbs/reader metadata.
- Prose: Source Serif 4, 18 px desktop / 16-17 px mobile, line-height approx. 1.7; a correct rhythm of paragraphs and headings; lists, quotes, footnotes and links have clear semantics.
- Heading levels are semantic: `h1` document, `h2` chapters, `h3` subsections. No manual swapping of the hierarchy for visual effect.
- Code: JetBrains Mono, a distinct neutral background, a copy button; only **the inner code block** may scroll horizontally. Tables: legible headers, subtle stripes/separators, horizontal scrolling inside the table on mobile (not the whole page), dark mode compatibility.
- Rendered Markdown and HTML must preserve semantics and safe isolation of the source; the new shell look must not break embedded HTML bundles, the PDF preview or the available sharing actions.
- Table of contents / properties / version history: **one optional `ReaderInspector`** (a panel on the right on wide screens, a drawer/sheet on small ones), **closed** by default unless the user previously deliberately opened it. It is a document tools panel, **not a second global navigation sidebar**.
- **Clear affordance:** a `Table of contents` button with a panel icon and a clear `aria-expanded` state, a close button in the panel, preference persistence only where it makes sense.
- Versions/comparison: we use existing capabilities; the comparison UI must not uncontrollably impose three fixed columns on the reader at 1024 px.

---

## 9. The "Projects" screen: projects play the lead role

**Goal:** see the projects quickly and go to the chosen project, without reading large empty cards.

- **Header:** a short title `Projects` and only the necessary helper information. A sentence like "Containers for documents. You invite by email…" is **contextual help or an empty state**, not a mandatory tall description above every list.
- **Shared toolbar:** `+ New project`, search, sort, filter (e.g. mine / shared, if it exists). No additional button on the opposite side of a large description.
- **Default desktop:** a dense project list; a row contains the name, a short description (if any), the number of documents, members, the role and `…`. Show the role with an ordinary, legible badge, not spread-out uppercase at the edge of a huge card.
- **Desktop optionally:** card/grid as a deliberately chosen view, but **not** 150-pixel cards for a single name and two counters. The view switch is shared in `PageToolbar`, not a separate panel.
- **Mobile:** one project as a compact card/row with the name, metadata and an accessible `…`; no table that requires horizontal scrolling.
- Clicking an item opens the project. Project editing and member management actions are in `…` or the local toolbar of the **details**, not on every global screen.
- Roles/permissions are **information**, not an alternative navigation. `No role` must not look like an action; if the status means limited capabilities, show the available permissions in clear text.

### 9.1. Single project view

- Breadcrumbs `Projects / Project name`.
- One header: the project name + role/status as helper information.
- One project toolbar: add/assign document, invite/manage members (when permitted), a menu with the remaining actions.
- The main part of the screen = **the project's documents**. The members panel, settings, description and permissions are presented as **collapsible sections, details tabs or an optional drawer**, never all at once as permanent sidebars.
- A folder/collection tree, if the project has one, is implemented in the **data view** or a section of the current navigation tree (depending on the actual semantics), not as another global column.

---

## 10. Administration, settings and special screens

- Administration has the same `AppShell`; `Users`, `Review`, `CDN`, `Audit` are nested navigation in the sidebar. The previous always-visible tab strip **must not duplicate** the same items.
- Administration pages may be denser; `DataTable`, filtering and bulk selection are preferred. For bulk actions a **contextual selection toolbar** appears instead of adding another permanently visible bar.
- Account settings, language, theme, sign-out: one avatar menu with logical groups; settings are edited on a dedicated page if the form is larger.
- Anonymous screens (public link, password, login, reset, setup) **do not show unavailable global navigation**; they use `PublicShell` / `CenteredCard` with the same typography, colours and controls.
- SSO/sharing components keep the actual access logic; moving options into a menu **does not change the authorisation rules**.

---

## 11. Collapsing and revealing: it must be visible that you can

Not every panel needs a chevron, but the user must understand that they can open/close it.

| Object | Trigger | State / behaviour |
| --- | --- | --- |
| Main sidebar | a visible `panel-left-open/close` button, tooltip and `aria-label` | expanded / collapsed; remembered on desktop |
| Navigation branch | chevron + group button with `aria-expanded` | chevron changes direction, a light height animation or instant under reduced motion |
| Filters | a labelled `Filters` button, active counter | popover / sheet; `Clear`, `Apply` only if the filters require it |
| Table of contents | `Table of contents` + panel icon | drawer/panel with a close control |
| Details section | header with a chevron | `Disclosure`; visible open state |
| Action menu | `…` button with an accessible name | desktop menu / mobile action sheet |

- Collapsing **must not remove the ability** to perform an action: collapsed navigation needs tooltips/flyouts; a closed reader panel can be opened from one obvious place.
- For every disclosure control: `aria-expanded`, `aria-controls`, a natural tab order, Escape where appropriate, visible focus. "Navigate" must be distinguished from "expand".
- `opacity-0` when hiding actions must be paired with the proper `pointer-events-none` and logical keyboard access; hiding only via `sm:` is not allowed; use `@media(hover:hover)` and `focus-within`.

---

## 12. Responsive behaviour: the contract for screens

| Width | Navigation | Content | Actions |
| --- | --- | --- | --- |
| **320-479 px** | drawer | one column, 12-16 px inset | one primary and `…`; full-screen sheets when necessary |
| **480-767 px** | drawer | one column, adaptive lists | text CTA + overflow menu |
| **768-1023 px** | collapsed 64 px rail / overlay | concise lists, full-width reader | compact toolbar, overflow |
| **1024-1439 px** | expanded 256 px or 64 px | typical dashboard | one visible set of actions |
| **1440+ px** | expanded 256 px or 64 px | wide content with an appropriate limit, reader up to 1100 px | no artificial multiplication of columns |

- Breakpoints mean **a change of pattern**, not just a change of padding. If the container width is critical (e.g. a dialog inside a panel), prefer `@container` rather than inferring from the viewport alone.
- Mobile: no horizontal scroll at the `html/body` level, no forms hidden behind an open keyboard, correct `dvh`, safe areas and sticky actions when the form requires it.
- A 390 px phone and a 1024 px wide touch tablet **do not need to have the same UI**; hover capability detection is based on `hover/pointer`, not on width.
- Moving between breakpoints and rotating the screen must not reset the document selection, local filters, the reading position or an operation in progress, unless that is unavoidable.
- Lists may switch `table → rows/cards`. **The same data sources and actions**, a different presentation.

---

## 13. Interactions, animation, affordance

- Animations should signal a change of state, not decorate. Usually **120-220 ms**, easing `cubic-bezier(0.2, 0.8, 0.2, 1)`; do not use `transition-all` as the standard.
- The sidebar may animate its width, **but without content jumping**, loss of focus and costly layout recalculations on every page.
- Hover is a discreet fill / a slight border change; do not lift cards en masse or scale icons by 10% on every click.
- An overlay has an appropriate `z-index`, a dimmed background and logical focus/scroll lock handling. Avoid problems with a fixed drawer inside an ancestor with `transform`; use a portal to the document if needed.
- `cursor-pointer` only where the object is actually interactive; a clickable row also has a semantic link/button, not just `onClick` on a `div`.
- Regardless of hover, all actions are reachable by keyboard and on a touch screen. The `…` icon has `aria-label="Document actions: …"`, no unlabelled buttons.
- Disabled, pending, uploading and error states are visible and explained; do not block buttons without information.

### 13.1. Anime.js: a mandatory but discreet language of motion

**MUST:** use **Anime.js** for deliberately designed animations, where motion genuinely improves the perception of a state change or the user's orientation. It is a tool for **micro-interactions and functional transitions**, not a reason to animate every element. Before integrating, check `package.json` and the library version in use; when installing, pick the current stable version and use only the API that matches it.

**Uses (in order of preference):**

| Element | Effect | Constraint |
| --- | --- | --- |
| Expanding and collapsing the sidebar tree | smooth reveal of children, subtle chevron rotation | no delay in the availability of links; do not animate a large tree all at once |
| Opening/closing the drawer and panels | a gentle **8-16 px** shift and fade | focus and Escape handling do not wait for the animation to end |
| Popover, menu, action sheet | a short fade + a small `translateY` | no "jumping out from afar" effect; the exit animation does not block the next action |
| Confirming a successful action | a single, subtle feedback at the icon/status | the message remains legible without motion too; no confetti |
| Changing a local filter / panel | a light change in the visibility of **only the content that changes** | no animating hundreds of rows, no change of scroll position |
| Sidebar expanded ↔ collapsed | a calm change in label visibility and rail state | do not costly animate the whole layout; no flashing and no double clicks |

**Motion budget:**

- Micro-feedback: usually **100-160 ms**. Menus, disclosures and popovers: **140-220 ms**. Drawer/sheet: usually **180-260 ms**. A longer duration requires justification and a usability test; do not add delays (`delay`) just for effect.
- Prefer animating **`transform` and `opacity`**. Avoid continuously animating `width`, `height`, `top`, `left`, `box-shadow`, large filters and `backdrop-filter`, especially in multi-item lists. If a disclosure must change height, animate only a small local panel, limit layout recalculations and measure smoothness.
- The most important interactive state (focus, active route, clickability, `aria-expanded`) applies **immediately**, not after the timeline ends. Animation is a presentation layer, not a driver of routing or business logic.
- **MUST NOT:** animate every list item on entering a page; create long sequences/staggers for documents and projects; use parallax, bouncing, looping pulses, perpetual shimmer outside justified loading, automatic scrolling or full-screen transitions that make it harder to find the content.
- `prefers-reduced-motion: reduce`: **disable spatial motion and sequences**, presenting the final state immediately (possibly with a harmless colour change). The preference must also be checked in the logic that starts Anime.js; global CSS rules alone do not guarantee that JavaScript-driven animations are disabled.
- In React, start animations only for the proper `ref` elements, after mounting, and **clean up/revert the scope or cancel active animations on unmount, route change and state change** according to the API of the chosen Anime.js version. Handle React Strict Mode and fast, repeated clicks; prevent leaks and overlapping animations.
- Do not mix two engines for **the same property of the same element** (e.g. Anime.js animates `transform` while Tailwind `transition-transform` tries to control it at the same time). Tailwind is responsible for the static look and simple hover/focus states; Anime.js for the few transitions that require control over time. Shared timing/easing parameters have one place of definition.
- Anime.js **is not a critical dependency for functionality**: even when an animation is skipped, the component must immediately reach the correct state. Do not block routing, uploads, saves and interactions on `finished`/`onComplete`.

**Aesthetic rule:** the user should *feel* the animation, not watch it. If it draws more attention than the document, project or button it serves, it is too strong.

---

## 14. Accessibility, semantics and quality

**MUST:**

- WCAG 2.2 AA for the UI: normal text contrast **≥4.5:1** (large ≥3:1), visibility of controls and focus, touch target as in §6.
- Landmarks `<header>`, `<nav aria-label="Main navigation">`, `<main id="main">`; **Skip to content**; one proper `h1` per screen (in the reader do not duplicate the document's `h1`).
- Keyboard: Tab/Shift+Tab, Enter/Space, Escape, clear focus, correct opening/closing of menus and focus restoration. `aria-current="page"` for the current route.
- Every image-only icon has a name; fields have a `<label>`; field errors are linked to a description (`aria-describedby`) and communicated without relying on colour.
- Distinguish a `navigation disclosure` (ordinary groups with `aria-expanded` buttons) from the **full ARIA treeview pattern**. If we implement `role="tree"`, all the required arrow, Home/End and roving focus behaviours must be provided; **do not add `role="tree"` for styling only**.
- Respect `prefers-reduced-motion`, the theme preference, increased text size and 200% zoom; where possible, reflow compliance at 400% without loss of functionality.
- Do not replace labels with unexplained icons, do not rely on the placeholder as a label, do not use too light a `font-weight` in small text.
- Verify the Polish and English locales, long project/document names, missing data, network errors, permission denial, files with unusual names.

---

## 15. Implementation in the existing React/Vite app: without rewriting the system

### 15.1. Target boundaries of responsibility

```text
src/
  styles/
    theme.css                # @theme + dark mode + base + markdown structure
    markdown-theme.ts        # one set of Markdown renderer classes
  components/
    shell/
      AppShell.tsx
      AppTopbar.tsx
      ContextBar.tsx
      AppSidebar.tsx
      SidebarGroup.tsx
      SidebarItem.tsx
    ui/
      Button.tsx
      IconButton.tsx
      PageHeader.tsx
      PageToolbar.tsx
      Menu.tsx
      ActionSheet.tsx
      Disclosure.tsx
      Drawer.tsx
      ...
    documents/               # document specialisations
    projects/                # project specialisations
    reader/                  # reader content, inspector, toolbar
```

The names above are **the target architecture**, not a statement that the files already exist. Before creating a new component, check the existing `ViewerChrome`, `AppNav`, `SidebarShell`, `SidebarNav`, `PageHeader`, `AssetRow`, `UploadStrip`, `AdminPage`, `ActionSheet`, `SegmentedToggle`, `EmptyState` and refactor instead of creating duplicates.

### 15.2. What we keep from the previous contract

- Tailwind CSS 4 and the Vite integration; the central `src/styles/theme.css` and `src/styles/markdown-theme.ts`.
- Reusable components, semantic tokens, light/dark, focus-visible, reduced motion, empty/loading/error states, skeletons that reproduce the geometry, `dvh`, protection against hover-only on touch.
- `Source Serif 4` for actual reading and `JetBrains Mono` for code; a reader with a maximum width of **1100 px**.
- Semantically unambiguous actions, a row that opens the resource, a separate rename, a shared set of actions for desktop/mobile.

### 15.3. What we deliberately replace

| Until now | New contract |
| --- | --- |
| Main navigation inline in `ViewerChrome` | the main tree in `AppSidebar` |
| A screen-dependent sidebar, often as filters | one global navigation sidebar, context in the toolbar or an overlay |
| Navy gradient topbar | neutral, flat app chrome |
| Orange as the link/focus colour | interaction blue; orange only as a sparing ICS mark |
| Serif as the default text on many pages | system sans for the whole UI; serif only for prose |
| Upload as a huge visible panel | upload as a primary action + an on-demand dropzone |
| Documents as mandatory large index cards | a compact data list, a card only where justified |
| Projects as tall cards with little content | compact rows or a considered data layout |
| Admin tabs duplicating the menu | one navigation in the sidebar |
| Many individual panels | unified `Drawer`, `Disclosure`, `Menu`, `ActionSheet` |

### 15.4. Migration order (small, safe steps)

1. **Inventory:** a list of screens, toolbars, sidebars, actions, existing dependencies and uses of colours/fonts; a map of duplicates.
2. **Tokens and typography:** new `@theme`, light/dark, font-ui, font-reading; contrast audit. Do not mix new and old utility classes without a planned migration.
3. **Shell:** `AppShell`, sidebar, tree, desktop/mobile, topbar, contextbar, focus and width management. Connect routing and permissions without changing endpoints.
4. **Patterns:** `PageHeader`, `PageToolbar`, `Menu/ActionSheet`, lists, disclosure, upload entry point; remove divergent local implementations.
5. **Screens in order:** Documents → Projects → project view → reader/collections → Administration → anonymous views.
6. **Clean-up:** remove dead components and styles, broken token references, unnecessary panels and old rules. Do not leave two active navigation systems in the code.
7. **Subtle animations:** integrate Anime.js in the shared `Disclosure`, `Drawer`, `Menu` components and the sidebar according to §13.1; do not build local, divergent animations for each page.
8. **Validation:** unit tests of action logic, routing, responsiveness, accessibility, visual regressions, reduced motion and the real user flow.

**Do not carry out the frontend rebuild by a one-off mass replacement of JSX without reviewing the flows.** The migration is iterative, but in every completed section **one** interface model must apply, not the old one next to the new one.

---

## 16. Protecting code consistency and quality

- In components, use Tailwind utilities from our tokens; `clsx`/the existing helper for variants. Do not add CSS-in-JS, a new UI library or a global framework "as a shortcut".
- **Deliberate exception:** Anime.js is an allowed and preferred animation library according to §13.1. Do not introduce parallel motion libraries for the same interactions.
- The `@theme` configuration is the source of truth. If an existing token name changes its semantics, **migrate its uses** instead of leaving an alias with a misleading name (`navy` as a light background, etc.).
- Spacing, radius and font values come from the agreed scale; exceptional values are deliberately described and reviewed.
- **Non-existent classes** (`bg-card` without a definition) and implicit fallbacks are forbidden. Verify the resulting CSS / screenshots.
- In CI or lint, add rules restricting stock palettes in JSX, hex values in components, unnecessary `transition-all`, unlabelled icon-only buttons and duplication of main bars and layouts (the last item partly through review / integration tests).
- No UI refactoring may remove access control. The sidebar filters visibility by permissions, but **the backend must still enforce every permission**.
- The rules in this document are requirements, but they **do not justify** regressions in uploading, SSO/public publication, versioning, GitLab sync, sharing or opening HTML/PDF/Markdown.

---

## 17. Acceptance scenarios and Definition of Done

### 17.1. Manual minimum (MUST)

- [ ] **Desktop 1440 × 900:** on entering Documents I see the title, concise actions and **the first documents without scrolling past a huge upload box**.
- [ ] **Desktop 1440 × 900:** on entering Projects I see a list of several projects with the name, number of files, members and role; the cards/rows are not oversized.
- [ ] **Sidebar:** I collapse it to icons and expand it; the active state, tooltip/flyout and trees work; the preference is kept when moving between screens.
- [ ] **Navigation:** Documents/Projects/Administration do not appear simultaneously in the topbar and the sidebar as two menus.
- [ ] **Upload:** I can pick a file from the button and drag a file, and the choice of publication mode is understandable.
- [ ] **Reader:** the text is legible, no double `h1` appears, I can hide the sidebar and open/close the table of contents.
- [ ] **Administration:** I find the sections in the sidebar, without a duplicated global set of tabs.
- [ ] **320, 375, 390, 768, 1024, 1280, 1440 and 1920 px:** no unintended horizontal scroll, no truncated CTAs/names, an appropriate navigation model.
- [ ] **Touch on a tablet:** every action is available without hover; the action sheet or labelled menu works.
- [ ] **Keyboard:** I can move through the sidebar, trees, toolbar, menus, upload and dialogs; Escape and focus restoration work.
- [ ] **Light/dark/system:** good contrast, visible focus, no flicker or sudden mix of colours when switching.
- [ ] **Anime.js:** the drawer, tree and menus have fast, discreet animations without lag, without blocking clicks, scrolling and navigation; repeated clicks do not break the state.
- [ ] **Reduced motion:** `prefers-reduced-motion: reduce` disables spatial animations on the JavaScript side too; all states are immediately reachable and complete.
- [ ] **Zoom 200%, a long Polish/English title, an empty list, a network error, loading:** the layout does not fall apart and the user knows what to do.
- [ ] **Permissions:** a user without the admin role does not see unavailable sections; no authorisation changes in the API.
- [ ] **Different formats:** Markdown, PDF, HTML bundle, collections and data coming from GitLab remain available.

### 17.2. Automation: expected checks

- Component tests: active/expanded, keyboard interactions, closing the drawer, mobile/desktop action parity, permissions in menus.
- Animation tests: `prefers-reduced-motion`, fast open/close/open, unmounting during an animation, no input blocking and no conflicts between Anime.js and CSS transitions.
- E2E tests: the Documents → document → project path; the create/upload flow; mobile drawer navigation; dark theme; no divergence of actions.
- a11y tests (e.g. axe) on representative screens and dialogs; an additional manual review of focus/hover/touch.
- Regression screenshots: documents, projects, reader, administration, empty state in light and dark, mobile and desktop.
- The project build and the current test set must pass **without disabling assertions for convenience**. We do not assume command names or the test framework before checking the repository's `package.json`.

### 17.3. Quality criterion for a single screen

Before accepting a PR, answer **YES** to all the questions:

1. Does the main content of the screen have a clearly higher priority than the controls?
2. Can you point to **one** obvious place for the view's primary actions?
3. Are there no two navigation sidebars and no duplicated main menus?
4. Does every expandable element **look expandable**?
5. After collapsing elements, can the user still reach all functions?
6. Does the list show plenty of useful content without unnecessarily tall cards?
7. Does the screen work with a keyboard, touch, in light/dark and at a width of 320 px?
8. Were existing tokens and shared components used, without yet another stylistic variant?
9. Is the document text comfortable to read, and does the UI avoid mixing the prose font with the controls?
10. Has no existing flow and no permission been broken?
11. Does Anime.js support orientation and micro-interactions without delaying work, and does it correctly respect reduced motion?

**A missing YES to even one question means a fix or a documented design decision is required before merge.**

---

## 18. Instructions for the agent implementing the changes

> **Carry out the contract as a coherent rebuild of the interface architecture, not as a cosmetic reskin.** First examine the current routing, component structure, `theme.css`, `markdown-theme.ts`, page layout, permission models and tests. Find every place with a duplicated navigation, toolbar, panel and button pattern. Propose an old → new mapping and migrate screen by screen. Preserve the logic, data, accessibility and existing functions. Use one AppShell, a collapsible sidebar with a tree, a small global topbar, contextual breadcrumbs and single toolbars. **Apply Anime.js selectively for subtle, pleasant micro-interactions (§13.1), never at the expense of navigation speed, keyboard handling or reduced motion.** Evaluate the implementation **on real screenshots** for desktop and mobile, not just on a passing compile. Do not stop at "the component looks similar": go through the full acceptance scenarios from §17.

**The ultimate ICS rule:** *first I see what I came for; then what I can do with it; only at the end the rest of the system.*

---

## 19. Implementation map

| Concern | Where |
| --- | --- |
| Tokens, dark mode, base styles, Markdown structure | `frontend/src/styles/theme.css` (stock palettes, sizes, radii and shadows are switched off; `src/styles/designTokens.test.ts` rejects stray utilities) |
| Web fonts (Source Serif 4, JetBrains Mono, Latin subsets, self-hosted) | `frontend/src/styles/fonts.css` |
| Markdown element classes | `frontend/src/styles/markdown-theme.ts` |
| Theme preference (light, dark, system) | `frontend/src/lib/theme.ts` and the pre-paint script in `frontend/index.html` |
| Logo, favicons, app icons (`#FF5500` mark, re-export with `node brand/export.mjs`) | `frontend/public/` (`logo.svg` is the source geometry, `favicon.svg` the hand-tuned 16-31 px variant, usage rules in `frontend/public/brand/README.md`); in the app `frontend/src/components/BrandMark.tsx` |
| Motion (Anime.js WAAPI, reduced motion, presence) | `frontend/src/lib/motion.ts` |
| App shell: sidebar, global bar, breadcrumb slot, drawer, command palette | `frontend/src/components/shell/` (`AppShell`, `AppSidebar`, `AppTopbar`, `PageContext`, `Page`, `CommandPalette`, `AccountMenu`, `NotificationsButton`, `navModel`) |
| UI primitives | `frontend/src/components/ui/` (`Button`, `IconButton`, `useTooltip`, `Menu` + `ActionSheet` over one `MenuAction` model, `Popover`, `Sheet`, `Drawer`, `Dialog`, `Disclosure`, `ChipTabs`, `Badge`, `DataList`, `PageHeader`, `PageToolbar`, `PanelSection`, `AppLink`, `useOverlay`, `floating`) |
| Documents list, filters, upload | `frontend/src/components/documents/`, `frontend/src/lib/useAssetFilter.ts` (scope from the sidebar, filters from the toolbar) |
| Reader, inspector, outline | `frontend/src/components/reader/` |
| Projects | `frontend/src/components/projects/`, `frontend/src/views/ProjectDetail/` |
| Admin screens (review queue, audit log, doc types, CDN, users) | `frontend/src/views/Admin*.tsx`, `frontend/src/views/admin/`, `frontend/src/views/adminAudit/`; audit references resolved to names and app links in `backend/app/services/audit_labels.py` |
| E-mail (all messages, light and dark) | `backend/app/email_templates.py` (frame, palette repeated from `theme.css`, `e-*` dark-mode classes, buttons) and `backend/app/email_templates_notify.py` (notification digest); change them together with the tokens |
| Sharing | `frontend/src/components/ShareDialog.tsx`, `frontend/src/components/share/` |
