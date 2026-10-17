# ADR-0009: English first, UI translated through i18n

**Status:** Accepted, 2026-09-24.
**Decision owners:** Owner.
**Scope:** all of `ics` (backend, frontend, docs, ADRs) and `ics-mcp`
(code, tool descriptions, `help_md`, README).

## Context

The project grew as an internal tool for a Polish team. Roughly a thousand
backend comment and docstring lines, about 600 frontend comment lines, 67
API error messages, the whole UI and the MCP tool descriptions are in
Polish, mixed with English. The repositories are being prepared for an
open-source release.

## Problem

Outside contributors cannot read the code or use the UI, and the mix of
languages makes both look unfinished. Options considered:

1. **Code and docs in English, UI stays Polish.** Smallest effort, but the
   product stays unusable for non-Polish users.
2. **Everything in English, UI through i18n (pl, en).** Largest effort,
   one consistent language for contributors and a usable product for
   both audiences.
3. **Only README and docs in English.** Least work, code stays mixed.

## Decision

Option 2:

- Code comments, docstrings, identifiers, log messages and commit messages
  are English.
- API errors carry English `detail` plus a stable machine-readable `code`;
  clients translate by `code`, never by parsing `detail`.
- The UI has no hard-coded user-visible strings. Every string comes from
  the i18n catalogue with `pl` and `en` locales kept in sync (same key
  set, enforced by a test). Locale follows the browser with English as the
  fallback; dates and numbers are formatted with the active locale.
- User-facing e-mails and notifications are rendered per locale as well
  (backend catalogue and locale resolution: ADR-0011).
- README, docs and new ADRs are English; existing ADRs are translated
  when the docs are prepared for publication. A Polish README may exist as
  a secondary file.
- `ics-mcp` tool descriptions, server instructions and `help_md` are
  English.

## Reactivation trigger

A third UI language, or a decision to drop the Polish locale.

## Consequences

- Translation work is split per package so each change stays reviewable.
- Adding a UI string now means adding a key to every locale file.
- Error handling in the frontend switches from `detail` text to `code`.
